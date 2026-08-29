#!/bin/sh
set -e

echo "=== [TARS Container Entrypoint] Initializing ==="

# Ensure storage and data directories readiness
mkdir -p "${TARS_STORAGE_DIR:-/app/storage}" /app/data 2>/dev/null || true

# Check database migration capability and run migrations
if command -v alembic >/dev/null 2>&1 && [ -f "/app/alembic.ini" -o -f "alembic.ini" ]; then
    echo "=== Running Database Migrations (Alembic) ==="
    alembic upgrade head || {
        echo "WARNING: Alembic migration encountered an error or DB not ready."
    }
fi

echo "=== Starting TARS Application Server ==="
exec "$@"
