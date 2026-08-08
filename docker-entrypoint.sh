#!/bin/bash
set -e

# Run migrations, then hand control to whatever this container was asked to run.
#
# The `exec "$@"` on the last line is the important part, and its absence was a
# real bug. This script used to end by exec'ing uvicorn directly, which silently
# discarded the `command:` every other service sets -- so the relay and the
# consumers both started an API server instead of doing their jobs. Nothing
# errored: three copies of the web app ran, no events were ever relayed to
# Redis, no alerts were raised, and the dashboard projection never updated.
# A `command:` that is quietly ignored is the worst kind of misconfiguration,
# because every container reports healthy.
#
# Migrations are opt-in per service rather than automatic. Three containers
# starting together would otherwise race on the same upgrade; Alembic takes a
# lock, so the losers block or fail on a cold start for no reason. Only the api
# service sets RUN_MIGRATIONS=1, and the schema is ready before it serves.

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "Running database migrations..."
  alembic upgrade head
  echo "Migrations complete."
fi

exec "$@"
