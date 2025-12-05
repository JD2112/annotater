# Use Python 3.10 slim image
FROM python:3.10-slim

# Install system dependencies including bedtools and build dependencies
RUN apt-get update && apt-get install -y \
    bedtools \
    build-essential \
    zlib1g-dev \
    libbz2-dev \
    liblzma-dev \
    libcurl4-openssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY streamlit_app/ ./streamlit_app/
COPY data/ ./data/

# Create temp directory
RUN mkdir -p /tmp/annotator && chmod 777 /tmp/annotator

# Expose Streamlit port
EXPOSE 8501

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl --fail http://localhost:8501/_stcore/health || exit 1

# Set environment variables
ENV STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=poll \
    STREAMLIT_SERVER_ENABLE_CORS=false \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Run Streamlit app as a module
CMD ["python", "-m", "streamlit", "run", "streamlit_app/streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
