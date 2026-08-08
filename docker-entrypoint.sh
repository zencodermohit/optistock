#!/bin/bash
set -e

echo "Waiting for PostgreSQL to start..."
# Note: we use pg_isready or just rely on docker-compose depends_on condition
# We'll run alembic upgrade head
echo "Running database migrations..."
alembic upgrade head

echo "Starting Uvicorn server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
