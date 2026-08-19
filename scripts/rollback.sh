#!/usr/bin/env bash
#
# Put the previous version back.
#
#     ./scripts/rollback.sh --list          what has been deployed here
#     ./scripts/rollback.sh                 back to the previous deploy
#     ./scripts/rollback.sh <sha>           back to a specific one
#
# Until now the only way back from a bad deploy was to work out by hand what
# the last good commit was, check it out on the server, and rebuild -- at
# exactly the moment when the site is broken and nobody is thinking clearly.
# This is that, written down and rehearsed.
#
# ── WHAT THIS DOES NOT DO ───────────────────────────────────────────────────
#
# It rolls back CODE. It does not roll back the DATABASE, and on this project
# those are different questions with different answers.
#
# Migrations run automatically on deploy, inside the api container's entrypoint.
# So if the deploy you are undoing added a column, rolling the code back leaves
# that column in place -- harmless, because the old code simply ignores it. That
# is the common case and this script handles it fine.
#
# The dangerous case is a migration that REMOVED or TRANSFORMED something. The
# old code expects what is no longer there, and no amount of code rollback
# brings the data back. Every revision here does have a downgrade(), but a
# downgrade that drops a column is not a recovery: it destroys whatever was
# written into it since. For that case the answer is the backup, not this
# script, and it says so below rather than letting you find out.
#
# ── WHY REBUILD RATHER THAN KEEP OLD IMAGES ─────────────────────────────────
#
# Retagging a previously built image would be faster. It would also mean the
# rollback path is only as good as whatever images happen to still be on a 20 GB
# disk that prunes itself, and discovering the one you need was cleaned up is a
# discovery for a better day than this one. A rebuild takes about three minutes
# here and always works.

set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/ubuntu/project_IV}"
HISTORY="${PROJECT_DIR}/.deploy-history"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1/health}"

cd "${PROJECT_DIR}"

if [ "${1:-}" = "--list" ]; then
  echo
  echo "  Deploys recorded on this host (newest first):"
  echo
  if [ -s "${HISTORY}" ]; then
    tac "${HISTORY}" | head -15 | while read -r line; do
      sha=$(echo "${line}" | awk '{print $2}')
      subject=$(git log -1 --format=%s "${sha}" 2>/dev/null || echo "(commit not present locally)")
      printf "    %s  %s\n        %s\n" "$(echo "${line}" | awk '{print $1}')" "${sha}" "${subject}"
    done
  else
    echo "    Nothing recorded yet. The history file starts filling on the next deploy."
  fi
  echo
  echo "  Currently running: $(git rev-parse --short HEAD) $(git log -1 --format=%s)"
  echo
  exit 0
fi

CURRENT="$(git rev-parse HEAD)"

if [ -n "${1:-}" ]; then
  TARGET="$1"
else
  # The previous DEPLOYED commit, which is not the same as the previous commit
  # in the log. Several commits can ship in one deploy, and the one before the
  # current HEAD may never have run anywhere.
  if [ ! -s "${HISTORY}" ]; then
    echo "No deploy history at ${HISTORY}, so there is no 'previous' to go back to." >&2
    echo "Name a commit explicitly:  $0 <sha>" >&2
    exit 1
  fi
  TARGET="$(tac "${HISTORY}" | awk '{print $2}' | grep -v "^$(git rev-parse --short "${CURRENT}")" | head -1)"
  if [ -z "${TARGET}" ]; then
    echo "Only one deploy is recorded; there is nothing earlier to return to." >&2
    exit 1
  fi
fi

git rev-parse --verify "${TARGET}^{commit}" >/dev/null 2>&1 || {
  echo "Unknown commit: ${TARGET}" >&2
  echo "Try:  git fetch origin && $0 ${TARGET}" >&2
  exit 1
}

echo
echo "  from  $(git rev-parse --short "${CURRENT}")  $(git log -1 --format=%s "${CURRENT}")"
echo "  to    $(git rev-parse --short "${TARGET}")  $(git log -1 --format=%s "${TARGET}")"
echo

# Name the migrations that will be left in place, because that is the one thing
# this cannot undo and the one thing most likely to matter.
MIGRATIONS="$(git diff --name-only "${TARGET}" "${CURRENT}" -- alembic/versions/ 2>/dev/null || true)"
if [ -n "${MIGRATIONS}" ]; then
  echo "  ⚠  Database migrations were added between these two commits:"
  echo "${MIGRATIONS}" | sed 's#alembic/versions/#      #'
  echo
  echo "     Rolling the code back does NOT undo them. If they only ADDED things,"
  echo "     the old code ignores them and you are fine. If any of them removed or"
  echo "     transformed data, this script cannot recover it and you want the"
  echo "     backup instead:  ./scripts/restore_db.sh --list"
  echo
fi

read -r -p "  Type 'rollback' to continue: " CONFIRM
[ "${CONFIRM}" = "rollback" ] || {
  echo "  Cancelled."
  exit 1
}

# Detached HEAD on purpose. A rollback is a temporary state you are meant to
# leave -- either by fixing forward and deploying again, or by deciding this is
# the new truth and moving the branch deliberately. Resetting main here would
# make an emergency silently rewrite the branch everyone else deploys from.
echo "==> checking out ${TARGET}"
git checkout --quiet --detach "${TARGET}"

echo "==> building (about three minutes on this instance)"
docker compose build

echo "==> restarting"
docker compose down
docker compose up -d

echo "==> waiting for health"
for _ in $(seq 1 40); do
  CODE="$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${HEALTH_URL}" || echo 000)"
  if [ "${CODE}" = "200" ]; then
    echo
    echo "  Rolled back to $(git rev-parse --short HEAD) and healthy."
    echo
    echo "  This host is now on a detached HEAD. Nothing on main has changed, so"
    echo "  the NEXT push will deploy main straight over this. If this rollback is"
    echo "  meant to stick, revert the bad commit on main and push that."
    echo
    exit 0
  fi
  sleep 5
done

echo >&2
echo "  Rolled back, but /health did not come up within 200s." >&2
echo "  docker compose ps ; docker compose logs --tail 50" >&2
exit 1
