# AnnotateR production image.
#
# Multi-stage build:
# Stage 1: Build the modern React frontend with Node 20
# Stage 2: Production Python image with FastAPI backend, bedtools, and Polars-Bio
#
# Platform: pinned to linux/amd64 by default (ARG PLATFORM). The pinned
# polars-bio release provides manylinux x86_64 wheels only (no
# linux/aarch64 wheel).
ARG PLATFORM=linux/amd64

# --- Stage 1: Frontend Build ---
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Production Python Image ---
FROM --platform=${PLATFORM} python:3.12-slim

# System dependencies:
#   bedtools - required by BedtoolsEngine (2.31.1 in Debian)
#   curl     - required by container health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    bedtools \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies: installed from requirements.txt
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code & dependencies
COPY app.py ./app.py
COPY start-script.sh ./start-script.sh
COPY streamlit_app/ ./streamlit_app/
COPY data/examples/ ./data/examples/
COPY benchmarks/benchmark_engines.py ./benchmarks/benchmark_engines.py
COPY scripts/docker_smoke.sh ./scripts/docker_smoke.sh
RUN chmod +x ./scripts/docker_smoke.sh ./start-script.sh

# Copy built frontend assets from builder stage
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Non-root user setup for container security
# SciLifeLab Serve standard specifies UID 1000
RUN groupadd -g 1000 appgroup && \
    useradd -u 1000 -g appgroup -s /bin/bash -m appuser && \
    mkdir -p /tmp/annotator && \
    chown -R appuser:appgroup /app /tmp/annotator && \
    chmod 777 /tmp/annotator

# Default port for AnnotateR web service
EXPOSE 8000 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl --fail http://localhost:8000/api/metadata || curl --fail http://localhost:8501/_stcore/health || exit 1

ENV PYTHONUNBUFFERED=1

# Run as non-root user
USER appuser

# Entry point: runs the start-script.sh (SciLifeLab Serve requirement for Custom Apps)
ENTRYPOINT ["./start-script.sh"]

