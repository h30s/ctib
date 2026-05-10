# ─── CTIB — Production Dockerfile ───
# Optimized for Railway free-tier deployment
FROM python:3.11-slim AS base

# Security: run as non-root
RUN groupadd -r ctib && useradd -r -g ctib ctib

WORKDIR /app

# System deps (curl for healthcheck)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps first (cache layer)
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . 2>/dev/null || true

# Copy full project
COPY . .

# Install again with full source
RUN pip install --no-cache-dir -e .

# Set ownership
RUN chown -R ctib:ctib /app

# Switch to non-root
USER ctib

# Railway injects PORT env var
ENV PORT=9000
EXPOSE ${PORT}

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/api/health || exit 1

# Run — Railway sets PORT, we respect it
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT}
