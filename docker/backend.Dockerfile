FROM python:3.12-slim-bookworm

# ---- System dependencies ----
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ---- Create non-root user ----
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# ---- Install dependencies (layer-cached separately from source) ----
COPY backend/pyproject.toml ./pyproject.toml
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir ".[dev]" 2>/dev/null || \
    pip install --no-cache-dir .

# ---- Copy source ----
COPY backend/src ./src
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini

# ---- Set up package in editable mode ----
RUN pip install --no-cache-dir -e .

# ---- Switch to non-root user ----
USER appuser

# ---- Health check ----
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "netacheck.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-config", "/dev/null"]
