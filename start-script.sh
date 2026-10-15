#!/bin/bash
set -e

# SciLifeLab Serve startup script for AnnotateR
# This script is executed by SciLifeLab Serve when deployed as a Custom App.

PORT="${PORT:-8000}"

echo "Starting AnnotateR on port ${PORT}..."
exec uvicorn streamlit_app.api_server:app --host 0.0.0.0 --port "${PORT}"
