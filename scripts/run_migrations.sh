#!/usr/bin/env bash
set -eo pipefail

echo "================================================================"
echo "🚀 [TARS Startup] Database Migration & Server Bootstrapper"
echo "================================================================"

# If PostgreSQL is configured, wait for database server connectivity
if [[ "${TARS_DATABASE_URL}" == *"postgresql"* ]]; then
  echo "🔍 Detecting PostgreSQL database configuration..."
  
  # Extract host and port using Python URL parsing helper
  DB_HOST=$(python3 -c "from urllib.parse import urlparse; u = urlparse('${TARS_DATABASE_URL}'); print(u.hostname or 'tars-db')")
  DB_PORT=$(python3 -c "from urllib.parse import urlparse; u = urlparse('${TARS_DATABASE_URL}'); print(u.port or 5432)")

  echo "⏳ Waiting for PostgreSQL at ${DB_HOST}:${DB_PORT} to accept connections..."
  MAX_RETRIES=30
  RETRY_COUNT=0

  while ! python3 -c "import socket; s = socket.create_connection(('${DB_HOST}', int('${DB_PORT}')), timeout=1); s.close()" 2>/dev/null; do
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ ${RETRY_COUNT} -ge ${MAX_RETRIES} ]; then
      echo "❌ Error: Timed out waiting for PostgreSQL after ${MAX_RETRIES} seconds."
      exit 1
    fi
    echo "   ... waiting for database (${RETRY_COUNT}/${MAX_RETRIES}s)"
    sleep 1
  done
  echo "✅ PostgreSQL connection established!"
fi

echo "🔄 Running Alembic database migrations (alembic upgrade head)..."
alembic upgrade head

echo "✅ Database schema is up-to-date!"
echo "================================================================"
echo "🌟 Launching TARS FastAPI Application..."
echo "================================================================"

# Exec into main process to receive OS signals cleanly (PID 1)
exec uvicorn main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
