#!/usr/bin/env bash
#
# Nightly database backup to S3.
#
# Runs on the server from cron. Dumps Postgres, compresses, uploads, and — the
# part most backup scripts skip — proves the dump is readable before calling it
# a success.
#
# WHY VERIFY. A backup you have never restored is a hypothesis. The classic
# failure is not a missing file, it is thirty perfectly-sized files that turn
# out to be truncated, or gzip streams that end mid-record, discovered on the
# day you need them. `gzip -t` plus a check for the marker pg_dump writes at
# the very end of a complete dump costs a second and turns "a file exists" into
# "a file that parses to the end exists".
#
# NO CREDENTIALS. The instance carries an IAM role (see terraform/backups.tf),
# so the AWS CLI gets temporary credentials from instance metadata. There is no
# key on this disk to leak.
#
# EXIT CODES. Non-zero on any failure, so cron mails the output and a silent
# failure is not possible. This is why `set -o pipefail` matters here: without
# it, `pg_dump | gzip` reports the exit status of gzip, and a database that has
# gone away produces a perfectly valid gzip of an error message.

set -euo pipefail

BUCKET="${BACKUP_BUCKET:-optistock-backups-220438080921}"
PROJECT_DIR="${PROJECT_DIR:-/home/ubuntu/project_IV}"
KEEP_LOCAL=2 # a couple of local copies for a fast restore; S3 holds the rest

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d)"
DUMP="${WORK}/optistock-${STAMP}.sql.gz"

# shellcheck disable=SC2064
trap "rm -rf '${WORK}'" EXIT

cd "${PROJECT_DIR}"

echo "[$(date -u +%FT%TZ)] dumping optistock_db"
docker compose exec -T db pg_dump -U optistock -d optistock_db --clean --if-exists \
  | gzip -9 >"${DUMP}"

# --- Verify before trusting -----------------------------------------------

if ! gzip -t "${DUMP}"; then
  echo "FAILED: dump is not a valid gzip stream" >&2
  exit 1
fi

# pg_dump ends a COMPLETE dump with this line. A dump truncated by a crash, a
# full disk or a killed container is still valid gzip and still has plausible
# size; it just stops in the middle. This is the cheap way to tell them apart.
if ! zcat "${DUMP}" | tail -5 | grep -q "PostgreSQL database dump complete"; then
  echo "FAILED: dump has no completion marker -- it is truncated" >&2
  exit 1
fi

SIZE="$(stat -c %s "${DUMP}")"
if [ "${SIZE}" -lt 100000 ]; then
  echo "FAILED: dump is only ${SIZE} bytes, which is too small to be real" >&2
  exit 1
fi

echo "[$(date -u +%FT%TZ)] verified: $((SIZE / 1024)) KB, complete"

# --- Upload ----------------------------------------------------------------

aws s3 cp "${DUMP}" "s3://${BUCKET}/daily/$(basename "${DUMP}")" --only-show-errors
echo "[$(date -u +%FT%TZ)] uploaded to s3://${BUCKET}/daily/$(basename "${DUMP}")"

# --- Keep a couple locally for a fast restore ------------------------------

mkdir -p "${PROJECT_DIR}/backups"
cp "${DUMP}" "${PROJECT_DIR}/backups/"
# shellcheck disable=SC2012
ls -1t "${PROJECT_DIR}/backups"/optistock-*.sql.gz 2>/dev/null \
  | tail -n +$((KEEP_LOCAL + 1)) | xargs -r rm --

echo "[$(date -u +%FT%TZ)] done"
