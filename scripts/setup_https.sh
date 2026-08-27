#!/usr/bin/env bash
#
# Free, browser-trusted HTTPS from Let's Encrypt. Run on the server.
#
#     sudo ./scripts/setup_https.sh 43-205-36-210.sslip.io you@example.com
#     sudo ./scripts/setup_https.sh --renew          (what cron calls)
#
# WHY THIS AND NOT THE CLOUDFLARE ORIGIN CERTIFICATE. The Cloudflare route
# needs a domain, and a domain costs money. This needs neither. It also
# produces a certificate browsers actually trust, which the origin certificate
# never was -- that one is trusted by Cloudflare alone and works only because
# the browser is talking to Cloudflare rather than to us.
#
# THE HOSTNAME. sslip.io resolves any address embedded in a name straight back
# to that address, with no account, no signup and nothing to renew:
# 43-205-36-210.sslip.io is 43.205.36.210. It is free forever and slightly
# ugly. Anything else that resolves here works identically -- a DuckDNS
# subdomain, or a real domain later -- and the only thing that changes is the
# argument to this script.
#
# RENEWAL IS THE POINT. A certificate is ninety days of working followed by an
# outage, unless something renews it. certbot's own systemd timer handles that,
# and the deploy hook below copies the new files where nginx expects them and
# reloads. The failure this avoids is subtle: renewal succeeds, certbot is
# happy, and nginx serves the expired copy it loaded in January because nobody
# told it to look again.

set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/ubuntu/project_IV}"
WEBROOT="${PROJECT_DIR}/nginx/certbot-webroot"
CERT_DIR="${PROJECT_DIR}/nginx/certs"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo -- certbot writes to /etc/letsencrypt." >&2
  exit 1
fi

install_certbot() {
  if ! command -v certbot >/dev/null 2>&1; then
    echo "==> installing certbot"
    DEBIAN_FRONTEND=noninteractive apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq certbot
  fi
}

# Copy the live certificate to where nginx reads it, and reload.
#
# Copied rather than symlinked on purpose: /etc/letsencrypt/live/ holds
# symlinks that only root can traverse, and the nginx container runs unprivileged
# against a read-only bind mount. A symlink chain it cannot follow presents as a
# missing certificate, which the entrypoint reports as "serving HTTP only" --
# technically accurate and completely baffling.
install_cert() {
  local domain="$1"
  local live="/etc/letsencrypt/live/${domain}"

  [ -d "${live}" ] || {
    echo "No certificate at ${live}" >&2
    return 1
  }

  mkdir -p "${CERT_DIR}"
  cp -L "${live}/fullchain.pem" "${CERT_DIR}/origin.pem"
  cp -L "${live}/privkey.pem" "${CERT_DIR}/origin.key"
  chmod 644 "${CERT_DIR}/origin.pem"
  chmod 600 "${CERT_DIR}/origin.key"

  echo "==> reloading nginx"
  cd "${PROJECT_DIR}"
  # restart, not `nginx -s reload`: the entrypoint is what decides whether the
  # 443 block exists at all, and it only runs on container start. On the very
  # first issuance a reload would re-read a config that still has no HTTPS in it.
  docker compose restart nginx >/dev/null
  sleep 3
  docker compose logs nginx --tail 20 2>&1 | grep "nginx-entrypoint" | tail -1
}

if [ "${1:-}" = "--renew" ]; then
  certbot renew --quiet --webroot -w "${WEBROOT}"
  # The domain this host actually serves, not whichever lineage sorts first.
  # `ls | head -1` was the original bug: once a second certificate existed,
  # 43-205-36-210.sslip.io sorted ahead of optistock.duckdns.org and this
  # installed the wrong one.
  DOMAIN=$(grep -E '^PUBLIC_HOST=' "${PROJECT_DIR}/.env" 2>/dev/null \
    | cut -d= -f2- | tr -d '"' | tr -d "'")
  if [ -z "${DOMAIN}" ]; then
    echo "PUBLIC_HOST is not set in ${PROJECT_DIR}/.env; nothing to install" >&2
    exit 1
  fi
  install_cert "${DOMAIN}"
  exit 0
fi

DOMAIN="${1:-}"
EMAIL="${2:-}"

if [ -z "${DOMAIN}" ] || [ -z "${EMAIL}" ]; then
  cat >&2 <<MSG
usage: sudo $0 <domain> <email>

  domain  a name that already resolves to this server. With no domain of your
          own, use the free sslip.io form -- your IP with dots turned to
          dashes, e.g. 43-205-36-210.sslip.io
  email   where Let's Encrypt warns you if renewal ever stops working. It is
          the only warning you will get.
MSG
  exit 2
fi

echo "==> checking ${DOMAIN} actually points here"
RESOLVED=$(getent hosts "${DOMAIN}" | awk '{print $1}' | head -1 || true)
MYIP=$(curl -fsS --max-time 10 https://api.ipify.org)
if [ "${RESOLVED}" != "${MYIP}" ]; then
  echo "FAILED: ${DOMAIN} resolves to '${RESOLVED:-nothing}', this host is ${MYIP}." >&2
  echo "Let's Encrypt will fail the same way, only slower and against your rate limit." >&2
  exit 1
fi
echo "    ${DOMAIN} -> ${RESOLVED}  OK"

install_certbot

mkdir -p "${WEBROOT}/.well-known/acme-challenge"
chmod -R 755 "${WEBROOT}"

# Prove the challenge path is actually reachable BEFORE asking the CA for
# anything. Let's Encrypt rate-limits failures per domain per hour, and burning
# that allowance on a misconfigured webroot means waiting rather than fixing.
echo "==> verifying the challenge path is served"
TOKEN="preflight-$(date +%s)"
echo "${TOKEN}" > "${WEBROOT}/.well-known/acme-challenge/${TOKEN}"
FETCHED=$(curl -fsS --max-time 15 "http://${DOMAIN}/.well-known/acme-challenge/${TOKEN}" 2>/dev/null || echo "")
rm -f "${WEBROOT}/.well-known/acme-challenge/${TOKEN}"
if [ "${FETCHED}" != "${TOKEN}" ]; then
  echo "FAILED: http://${DOMAIN}/.well-known/acme-challenge/ is not serving that directory." >&2
  echo "Deploy the current nginx config first, then re-run this." >&2
  exit 1
fi
echo "    challenge path reachable  OK"

echo "==> requesting the certificate"
certbot certonly \
  --webroot -w "${WEBROOT}" \
  -d "${DOMAIN}" \
  --email "${EMAIL}" \
  --agree-tos \
  --non-interactive \
  --keep-until-expiring

install_cert "${DOMAIN}"

# certbot's packaged timer already runs twice a day; it just does not know to
# copy anything into the container's view. This hook is what closes that gap.
echo "==> installing the renewal hook"
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
# Written with the domain resolved at RUN time, not baked in at write time.
#
# The previous version interpolated ${DOMAIN} into the hook, which froze
# whatever this script happened to pick on the day it was run. After the move
# from sslip.io to DuckDNS the host had two lineages, the hook still named the
# old one, and the next renewal would have copied a certificate for a name
# nobody visits and restarted nginx serving it -- every browser refusing the
# site, months later, with nothing having been touched in between.
#
# PUBLIC_HOST in the application's own .env is the single place the domain is
# already declared, so the hook reads that and cannot drift from it.
cat >/etc/letsencrypt/renewal-hooks/deploy/optistock.sh <<'HOOK'
#!/usr/bin/env bash
# Written by scripts/setup_https.sh. Runs after every successful renewal.
set -euo pipefail

ENV_FILE=/home/ubuntu/project_IV/.env
CERT_DIR=/home/ubuntu/project_IV/nginx/certs

DOMAIN=$(grep -E '^PUBLIC_HOST=' "${ENV_FILE}" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'")
if [ -z "${DOMAIN}" ]; then
  echo "renewal hook: PUBLIC_HOST is not set in ${ENV_FILE}; nothing to install" >&2
  exit 0
fi

LIVE="/etc/letsencrypt/live/${DOMAIN}"

# certbot sets RENEWED_LINEAGE to the lineage it just renewed. Ignore any
# other certificate on this host, so a stale lineage renewing cannot install
# itself over the one the site serves. Absent when run by hand, and installing
# the configured domain is then exactly what was wanted.
if [ -n "${RENEWED_LINEAGE:-}" ] && [ "${RENEWED_LINEAGE}" != "${LIVE}" ]; then
  exit 0
fi

cp -L "${LIVE}/fullchain.pem" "${CERT_DIR}/origin.pem"
cp -L "${LIVE}/privkey.pem"  "${CERT_DIR}/origin.key"
chmod 644 "${CERT_DIR}/origin.pem"
chmod 600 "${CERT_DIR}/origin.key"

cd /home/ubuntu/project_IV && docker compose restart nginx
echo "renewal hook: installed ${DOMAIN} and restarted nginx"
HOOK
chmod +x /etc/letsencrypt/renewal-hooks/deploy/optistock.sh

echo
echo "  HTTPS is live:  https://${DOMAIN}"
echo "  Renewal:        certbot's timer, twice daily; the hook reloads nginx."
echo "  Dry-run it:     sudo certbot renew --dry-run"
echo
