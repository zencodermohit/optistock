#!/usr/bin/env bash
#
# Keep a free DuckDNS subdomain pointing at this server.
#
#     ./duckdns_update.sh --check     show what DuckDNS has, change nothing
#     ./duckdns_update.sh             update it if the address has moved
#
# DuckDNS gives away a subdomain -- yourname.duckdns.org -- for nothing, with
# no card, no expiry and an update API that is one HTTP GET. That is the whole
# reason it is here rather than Cloudflare: Cloudflare's free plan is free, but
# it still needs a domain you own, and domains cost money.
#
# The instance carries an Elastic IP, so like the Cloudflare script this will
# report "unchanged" every single run under normal operation. That is the
# intended steady state. It earns its place the day the address does move --
# instance replaced, EIP released, destroy/apply -- when the subdomain would
# otherwise point at whoever AWS hands that address to next.
#
# CREDENTIALS live in /etc/optistock/duckdns.env, root-owned, chmod 600:
#
#     DUCKDNS_DOMAIN=yourname        the subdomain only, no .duckdns.org
#     DUCKDNS_TOKEN=...              from the DuckDNS home page
#
# The token is passed in the URL because DuckDNS offers no other way, which is
# also why it goes in a --data field of a POST here rather than on the command
# line: a token in a URL on a command line is a token in `ps` output and in the
# shell history of anyone who runs this by hand.

set -euo pipefail

CONFIG="${DUCKDNS_ENV:-/etc/optistock/duckdns.env}"

if [ ! -r "${CONFIG}" ]; then
  cat >&2 <<MSG
No config at ${CONFIG}

Create it (as root), chmod 600:

  DUCKDNS_DOMAIN=yourname      just the subdomain, without .duckdns.org
  DUCKDNS_TOKEN=...            the token shown on https://www.duckdns.org
MSG
  exit 1
fi

# shellcheck disable=SC1090
. "${CONFIG}"

for var in DUCKDNS_DOMAIN DUCKDNS_TOKEN; do
  if [ -z "${!var:-}" ]; then
    echo "FAILED: ${var} is not set in ${CONFIG}" >&2
    exit 1
  fi
done

FQDN="${DUCKDNS_DOMAIN}.duckdns.org"

# AWS is the authority on what address is attached to this instance, and the
# metadata service cannot be down independently of the instance itself.
# IMDSv2 wants a token first. The public lookup is for running this off EC2.
current_ip() {
  local t ip
  t=$(curl -fsS --max-time 5 -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 60" 2>/dev/null) || t=""
  if [ -n "${t}" ]; then
    ip=$(curl -fsS --max-time 5 -H "X-aws-ec2-metadata-token: ${t}" \
      "http://169.254.169.254/latest/meta-data/public-ipv4" 2>/dev/null) || ip=""
    [ -n "${ip}" ] && {
      echo "${ip}"
      return
    }
  fi
  curl -fsS --max-time 10 https://api.ipify.org
}

IP="$(current_ip)"
if ! printf '%s' "${IP}" | grep -qE '^([0-9]{1,3}\.){3}[0-9]{1,3}$'; then
  echo "FAILED: could not determine a public IP (got '${IP}')" >&2
  exit 1
fi

# What the world currently believes. Asking DNS rather than DuckDNS's API,
# because what actually matters is what a browser would resolve.
PUBLISHED="$(getent hosts "${FQDN}" 2>/dev/null | awk '{print $1}' | head -1 || true)"

if [ "${1:-}" = "--check" ]; then
  echo "  domain      ${FQDN}"
  echo "  resolves to ${PUBLISHED:-nothing}"
  echo "  this host   ${IP}"
  [ "${PUBLISHED}" = "${IP}" ] && echo "  IN SYNC" || echo "  OUT OF SYNC — a normal run would update it"
  exit 0
fi

if [ "${PUBLISHED}" = "${IP}" ]; then
  echo "[$(date -u +%FT%TZ)] ${FQDN} already ${IP}, nothing to do"
  exit 0
fi

echo "[$(date -u +%FT%TZ)] ${FQDN}: ${PUBLISHED:-unset} -> ${IP}"

# DuckDNS answers with the literal string "OK" or "KO". It returns HTTP 200
# either way, so the body is the only thing that says whether it worked --
# checking the status code here would call every failure a success.
RESPONSE="$(curl -fsS --max-time 15 \
  --data-urlencode "domains=${DUCKDNS_DOMAIN}" \
  --data-urlencode "token=${DUCKDNS_TOKEN}" \
  --data-urlencode "ip=${IP}" \
  "https://www.duckdns.org/update")"

if [ "${RESPONSE}" != "OK" ]; then
  echo "FAILED: DuckDNS replied '${RESPONSE}' (KO usually means a wrong token or domain)" >&2
  exit 1
fi

echo "[$(date -u +%FT%TZ)] DuckDNS accepted the update for ${FQDN} -> ${IP}"
