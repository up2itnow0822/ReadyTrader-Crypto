# ReadyTrader-Crypto Production Dockerfile
# Security-hardened, non-root runtime with proper healthchecks
#
# Usage:
#   docker build -t readytrader-crypto .
#   docker build --target mcp -t readytrader-crypto:mcp .
#   docker build --target api -t readytrader-crypto:api .

# =============================================================================
# Build stage
# =============================================================================
FROM python:3.12-slim-bookworm AS builder

WORKDIR /build

# Install build dependencies
# hadolint ignore=DL3008
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
# hadolint ignore=DL3013
RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# =============================================================================
# Base production stage (shared by MCP and API)
# =============================================================================
FROM python:3.12-slim-bookworm AS base

# Security: Create non-root user
RUN groupadd --gid 1000 readytrader && \
    useradd --uid 1000 --gid readytrader --shell /bin/bash --create-home readytrader

WORKDIR /app

# Security: Install only runtime dependencies
# hadolint ignore=DL3008
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy wheels from builder and install
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt && \
    rm -rf /wheels

# Copy application code
COPY --chown=readytrader:readytrader . .

# Security: Remove unnecessary files
RUN rm -rf \
    .git \
    .github \
    .gitignore \
    .venv \
    tests \
    docs \
    examples \
    coverage_html \
    htmlcov \
    Makefile \
    justfile \
    frontend/node_modules \
    vendor \
    mpc_signer \
    2>/dev/null || true

# Create data directory with correct permissions
RUN mkdir -p /app/data && chown -R readytrader:readytrader /app/data

# Security: Set restrictive permissions
RUN chmod -R 755 /app && \
    chmod -R 700 /app/data

# Environment defaults (secure by default)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PAPER_MODE=true \
    LIVE_TRADING_ENABLED=false \
    TRADING_HALTED=false \
    DEV_MODE=false \
    API_HOST=0.0.0.0 \
    API_PORT=8000

# Security: Switch to non-root user
USER readytrader

# Labels for metadata
LABEL org.opencontainers.image.title="ReadyTrader-Crypto" \
      org.opencontainers.image.description="AI-powered crypto trading MCP server with safety guardrails" \
      org.opencontainers.image.vendor="ReadyTrader" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/up2itnow/ReadyTrader-Crypto"

# =============================================================================
# MCP Server target (default)
# =============================================================================
FROM base AS mcp

# MCP uses stdio, no port needed
# Healthcheck: verify Python can import the server module
HEALTHCHECK --interval=60s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from server import mcp; from app.core.settings import settings; print('OK')" || exit 1

CMD ["python", "app/main.py"]

# =============================================================================
# API Server target
# =============================================================================
FROM base AS api

# Expose FastAPI port
EXPOSE 8000

# Healthcheck for API server
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import sys, urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=5); sys.exit(0)" || exit 1

CMD ["python", "-m", "uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000"]

# =============================================================================
# Combined target (runs API server, healthcheck matches)
# =============================================================================
FROM api AS production

# Default is API server with proper healthcheck
# Use --target mcp for MCP-only builds
