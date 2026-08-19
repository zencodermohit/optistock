#!/usr/bin/env bash
#
# Restore the database from a backup.
#
# The companion to backup_db.sh, and the reason that script exists. A backup
# procedure without a restore procedure is a filing system.
#
# Usage:
#   ./restore_db.sh --list                       what backups exist
#   ./restore_db.sh --latest                     restore the most recent
#   ./restore_db.sh optistock-20260818T....sql.gz   restore a specific one
#
# THIS IS DESTRUCTIVE. The dump is taken with --clean --if-exists, so applying
# it DROPs the current tables before recreating them. It therefore asks for
# confirmation and will not run unattended. That is deliberate: every other
# script here is safe to automate, and this one must never be.

set -euo pipefail

BUCKET="${BACKUP_BUCKET:-optistock-backups-220438080921}"
PROJECT_DIR="${PROJECT_DIR:-/home/ubuntu/project_IV}"

cd "${PROJECT_DIR}"

list_backups() {
  aws s3 ls "s3://${BUCKET}/daily/" --human-readable | sort -r
}

case "${1:-}" in
"" | --help | -h)
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
  ;;
--list)
  list_backups
  exit 0
  ;;
--latest)
  KEY="$(aws s3 ls "s3://${BUCKET}/daily/" | sort | tail -1 | awk '{print $4}')"
  [ -n "${KEY}" ] || {
    echo "No backups found in s3://${BUCKET}/daily/" >&2
    exit 1
  }
  ;;
*)
  KEY="$1"
  ;;
esac

WORK="$(mktemp -d)"
# shellcheck disable=SC2064
trap "rm -rf '${WORK}'" EXIT
LOCAL="${WORK}/${KEY}"

echo "Fetching ${KEY}"
aws s3 cp "s3://${BUCKET}/daily/${KEY}" "${LOCAL}" --only-show-errors

# Verify before destroying anything. Restoring from a corrupt dump would drop
# the live tables and then fail to recreate them, which is strictly worse than
# not restoring at all.
gzip -t "${LOCAL}" || {
  echo "ABORT: ${KEY} is not a valid gzip stream" >&2
  exit 1
}
zcat "${LOCAL}" | tail -5 | grep -q "PostgreSQL database dump complete" || {
  echo "ABORT: ${KEY} is truncated -- refusing to restore from it" >&2
  exit 1
}
echo "Verified: complete dump, $(($(stat -c %s "${LOCAL}") / 1024)) KB"

echo
echo "This will DROP the current contents of optistock_db and replace them"
echo "with ${KEY}."
read -r -p "Type 'restore' to continue: " CONFIRM
[ "${CONFIRM}" = "restore" ] || {
  echo "Cancelled."
  exit 1
}

# Stop the writers first. Restoring underneath a running API means the dump
# competes with live transactions for locks, and anything written between the
# DROP and the reload is lost without trace. nginx stays up so visitors get an
# error from the API rather than a dead socket.
echo "Stopping api, relay and consumers"
docker compose stop api relay consumers

echo "Restoring"
zcat "${LOCAL}" | docker compose exec -T db psql -U optistock -d optistock_db -v ON_ERROR_STOP=1 -q

echo "Restarting"
docker compose start api relay consumers

echo
echo "Restored from ${KEY}"
docker compose exec -T db psql -U optistock -d optistock_db -tAc \
  "select 'users=' || count(*) from users;"
