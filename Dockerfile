# AnnotateR production image.
#
# Platform: pinned to linux/amd64 by default (ARG PLATFORM). The pinned
# polars-bio release provides manylinux x86_64 wheels only (no
# linux/aarch64 wheel), so an arm64 build cannot resolve dependencies
# natively; on arm64 hosts Docker Desktop pulls the amd64 base and
# emulates it via QEMU. Do NOT override PLATFORM to another value unless
# a wheel exists for it — the build will fail at `pip install`. See
# docs/deployment.md.
ARG PLATFORM=linux/amd64
FROM --platform=${PLATFORM} python:3.12-slim

# System dependencies:
#   bedtools - required by BedtoolsEngine (Debian bookworm ships 2.31.1,
#              matching the validated environment; the container smoke
#              test asserts the version).
#   curl     - required by the HEALTHCHECK below.
# No compiler toolchain is needed: every pinned Python dependency has an
# official manylinux x86_64 wheel (verified against the pinned versions).
RUN apt-get update && apt-get install -y --no-install-recommends \
    bedtools \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
#   app.py                       - Serve entry-point shim (imports the real
#                                  app module; see docs/deployment.md)
#   streamlit_app/               - the application package
#   data/examples/               - bundled example inputs (no user data)
#   benchmarks/benchmark_engines.py - in-container benchmark smoke (CI)
#   scripts/docker_smoke.sh      - in-container smoke test (CI / local)
COPY app.py ./app.py
COPY streamlit_app/ ./streamlit_app/
COPY data/examples/ ./data/examples/
COPY benchmarks/benchmark_engines.py ./benchmarks/benchmark_engines.py
COPY scripts/docker_smoke.sh ./scripts/docker_smoke.sh
RUN chmod +x ./scripts/docker_smoke.sh

# Writable scratch directory for intermediate bedtools files
RUN mkdir -p /tmp/annotator && chmod 777 /tmp/annotator

# SciLifeLab Serve and local container deployments expect Streamlit on
# 8501 (http://localhost:8501).
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl --fail http://localhost:8501/_stcore/health || exit 1

ENV STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=poll \
    STREAMLIT_SERVER_ENABLE_CORS=false \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    PYTHONUNBUFFERED=1

# Serve entry point: the main application file MUST be named app.py in the
# working directory (SciLifeLab Serve requirement).
ENTRYPOINT ["python", "-m", "streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]