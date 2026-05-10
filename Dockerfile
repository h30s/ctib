# ─── CTIB — Production Dockerfile ───
FROM python:3.11-slim

# Security: run as non-root
RUN groupadd -r ctib && useradd -r -g ctib ctib

WORKDIR /app

# System deps (curl for healthcheck)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps from pyproject.toml
# We copy pyproject.toml first for Docker layer caching
COPY pyproject.toml ./

# Install deps declared in pyproject.toml (without editable install)
RUN pip install --no-cache-dir \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.32.0" \
    "pydantic>=2.0" \
    "httpx>=0.27.0" \
    "google-genai>=1.0.0" \
    "python-dotenv>=1.0.0" \
    "mcp[cli]>=1.0.0"

# Copy full project source
COPY . .

# Set PYTHONPATH so local imports (agents, schemas, mcp_servers) resolve
ENV PYTHONPATH=/app

# Set ownership
RUN chown -R ctib:ctib /app

# Switch to non-root
USER ctib

# Railway injects PORT env var; fall back to 9000
ENV PORT=9000
EXPOSE ${PORT}

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/api/health || exit 1

# Run
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT}
