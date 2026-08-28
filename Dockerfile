# syntax=docker/dockerfile:1.4

# =============================================================================
# Stage 1: Builder
# =============================================================================
FROM python:3.11-slim AS builder

# Install uv package manager binary from official image
COPY --from=ghcr.io/astral-sh/uv:0.6 /uv /uvx /bin/

# Configure Python & UV environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_SYSTEM_PYTHON=0

WORKDIR /app

# Copy dependency definition files first for optimal build cache
COPY pyproject.toml uv.lock README.md ./

# Install production dependencies only using cache mount
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Copy application source code and scripts
COPY tars ./tars
COPY main.py ./
COPY scripts ./scripts
COPY alembic.ini ./
COPY migrations ./migrations

# Install the application wheel into the virtualenv
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


# =============================================================================
# Stage 2: Production Runtime
# =============================================================================
FROM python:3.11-slim AS runtime

# Set runtime environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    TARS_STORAGE_DIR="/app/storage" \
    TARS_ENVIRONMENT="production"

# Install essential runtime tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root system user and group (UID/GID: 10001)
RUN groupadd -g 10001 tarsuser && \
    useradd -u 10001 -g tarsuser -s /bin/sh -M tarsuser

WORKDIR /app

# Create storage and data directories with proper non-root ownership
RUN mkdir -p /app/storage /app/data && \
    chown -R tarsuser:tarsuser /app/storage /app/data

# Copy isolated virtual environment from builder stage
COPY --from=builder --chown=tarsuser:tarsuser /app/.venv /app/.venv

# Copy application files
COPY --chown=tarsuser:tarsuser tars ./tars
COPY --chown=tarsuser:tarsuser main.py ./
COPY --chown=tarsuser:tarsuser scripts ./scripts
COPY --chown=tarsuser:tarsuser alembic.ini ./
COPY --chown=tarsuser:tarsuser migrations ./migrations

# Set executable permission on entrypoint scripts
RUN chmod +x /app/scripts/*.sh 2>/dev/null || true

# Switch to non-root execution
USER tarsuser

# Expose FastAPI application port
EXPOSE 8000

# Container healthcheck using fast HTTP probe
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Container entrypoint and startup command
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["uvicorn", "tars.main:app", "--host", "0.0.0.0", "--port", "8000"]
