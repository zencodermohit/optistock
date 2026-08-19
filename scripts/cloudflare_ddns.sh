#!/usr/bin/env bash
#
# Keep a Cloudflare A record pointing at this server.
#
# The instance carries an Elastic IP, so under normal operation the address
# never changes and this script will report "unchanged" every time it runs.
# That is the intended steady state, not a sign it is doing nothing. What it
# protects against is the case where the address DOES move -- the instance is
# replaced, the EIP is released and reallocated, terraform destroy/apply -- at
# which point the domain would otherwise point at somebody else's server until
# a human noticed.
#
# It is written to be boring on the happy path: one read, a comparison, and no
# write. Cloudflare rate-limits the API, and a dynamic-DNS script that PUTs the
# same value every five minutes is the usual way people find that out.
#
# CREDENTIALS live in /etc/optistock/cloudflare.env, root-owned and chmod 600,
# never in this file and never in the repository. The token should be a scoped
# API TOKEN with Zone:DNS:Edit on the one zone -- not the global API key, which
# can do anything to every zone and every domain on the account.
#
#     ./cloudflare_ddns.sh --check     validate config and credentials, write nothing
#     ./cloudflare_ddns.sh --dry-run   show what would change
#     ./cloudflare_ddns.sh             do it
#
# JSON is parsed with python3 rather than jq: python3 ships with Ubuntu and jq
# does not, and one fewer package to install on a 1 GB box is one fewer thing
# that can be missing at 3am.

set -euo pipefail

CONFIG="${CLOUDFLARE_ENV:-/etc/optistock/cloudflare.env}"
API="https://api.cloudflare.com/client/v4"

MODE="run"
case "${1:-}" in
--check) MODE="check" ;;
--dry-run) MODE="dry" ;;
"") MODE="run" ;;
*)
  echo "usage: $0 [--check|--dry-run]" >&2
  exit 2
  ;;
esac

# --- Config ----------------------------------------------------------------

if [ ! -r "${CONFIG}" ]; then
  cat >&2 <<MSG
No config at ${CONFIG}

Create it (as root), chmod 600:

  CF_API_TOKEN=...        scoped token, Zone:DNS:Edit on this zone only
  CF_ZONE_ID=...          Cloudflare dashboard -> your domain -> Overview -> Zone ID
  CF_RECORD_NAME=...      the full name, e.g. optistock.example.com
MSG
  exit 1
fi

# shellcheck disable=SC1090
. "${CONFIG}"

for var in CF_API_TOKEN CF_ZONE_ID CF_RECORD_NAME; do
  if [ -z "${!var:-}" ]; then
    echo "FAILED: ${var} is not set in ${CONFIG}" >&2
    exit 1
  fi
done

# --- What address are we actually on? --------------------------------------
#
# The instance metadata service is authoritative -- it is AWS telling us what
# it attached -- and does not depend on a third party being up. IMDSv2 wants a
# token first. The external lookup is a fallback for running this anywhere that
# is not EC2.

current_ip() {
  local token ip
  token=$(curl -fsS --max-time 5 -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 60" 2>/dev/null) || token=""
  if [ -n "${token}" ]; then
    ip=$(curl -fsS --max-time 5 -H "X-aws-ec2-metadata-token: ${token}" \
      "http://169.254.169.254/latest/meta-data/public-ipv4" 2>/dev/null) || ip=""
    [ -n "${ip}" ] && {
      echo "${ip}"
      return
    }
  fi
  curl -fsS --max-time 10 https://api.ipify.org
}

# Pull one field out of a Cloudflare response. Kept in one place so an API
# shape change is one edit, and so the token never reaches a command line where
# it could show up in `ps` output.
cf_get() {
  curl -fsS --max-time 15 -H "Authorization: Bearer ${CF_API_TOKEN}" \
    "${API}/zones/${CF_ZONE_ID}/dns_records?type=A&name=${CF_RECORD_NAME}"
}

json_field() {
  python3 -c '
import json, sys
data = json.load(sys.stdin)
if not data.get("success", False):
    errs = "; ".join(e.get("message", "?") for e in data.get("errors", []))
    sys.stderr.write("Cloudflare API error: " + (errs or "unknown") + "\n")
    sys.exit(1)
results = data.get("result") or []
if not results:
    sys.exit(3)
sys.stdout.write(str(results[0].get(sys.argv[1], "")))
' "$1"
}

IP="$(current_ip)"
if ! printf '%s' "${IP}" | grep -qE '^([0-9]{1,3}\.){3}[0-9]{1,3}$'; then
  echo "FAILED: could not determine a valid public IP (got '${IP}')" >&2
  exit 1
fi

RESPONSE="$(cf_get)"

set +e
RECORD_ID="$(printf '%s' "${RESPONSE}" | json_field id)"
LOOKUP=$?
set -e

if [ "${LOOKUP}" -eq 3 ]; then
  echo "FAILED: no A record named ${CF_RECORD_NAME} exists in this zone." >&2
  echo "Create it once in the Cloudflare dashboard; this script updates, it does not create." >&2
  exit 1
elif [ "${LOOKUP}" -ne 0 ]; then
  exit 1
fi

RECORD_IP="$(printf '%s' "${RESPONSE}" | json_field content)"
PROXIED="$(printf '%s' "${RESPONSE}" | json_field proxied)"

if [ "${MODE}" = "check" ]; then
  echo "  config      ${CONFIG}"
  echo "  record      ${CF_RECORD_NAME}"
  echo "  points at   ${RECORD_IP}"
  echo "  this host   ${IP}"
  echo "  proxied     ${PROXIED}"
  echo "  credentials OK"
  [ "${RECORD_IP}" = "${IP}" ] && echo "  IN SYNC" || echo "  OUT OF SYNC — a normal run would update it"
  exit 0
fi

if [ "${RECORD_IP}" = "${IP}" ]; then
  echo "[$(date -u +%FT%TZ)] ${CF_RECORD_NAME} already ${IP}, nothing to do"
  exit 0
fi

echo "[$(date -u +%FT%TZ)] ${CF_RECORD_NAME}: ${RECORD_IP} -> ${IP}"

if [ "${MODE}" = "dry" ]; then
  echo "  DRY RUN: not written"
  exit 0
fi

# PATCH, not PUT. PUT replaces the whole record and would silently drop the
# proxied flag and the TTL if they were not restated -- which, on a proxied
# record, means turning Cloudflare's TLS off as a side effect of a DNS update.
RESULT="$(curl -fsS --max-time 15 -X PATCH \
  -H "Authorization: Bearer ${CF_API_TOKEN}" \
  -H "Content-Type: application/json" \
  --data "{\"content\":\"${IP}\"}" \
  "${API}/zones/${CF_ZONE_ID}/dns_records/${RECORD_ID}")"

NEW_IP="$(printf '%s' "${RESULT}" | json_field content)"
if [ "${NEW_IP}" != "${IP}" ]; then
  echo "FAILED: Cloudflare accepted the request but the record reads ${NEW_IP}" >&2
  exit 1
fi

echo "[$(date -u +%FT%TZ)] updated and verified: ${CF_RECORD_NAME} -> ${NEW_IP}"
