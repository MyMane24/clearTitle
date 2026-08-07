# ── Build stage: frontend React SPA ───────────────────────────────────────────
FROM node:20-alpine AS frontend-build
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Runtime stage: FastAPI backend ─────────────────────────────────────────────
FROM python:3.11-slim

# System dependencies
# - gcc / build-essential: compile C extensions in some pip packages
# - libgomp1: OpenMP (used by numpy/OpenCV internals)
# - libglib2.0-0: required by some OpenCV headless builds
# - curl: used in health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    libgomp1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory — all relative paths in the app (uploads/, outputs/, data/) resolve here
WORKDIR /app

# Install Python dependencies first (separate layer for Docker cache efficiency)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Copy the React SPA (served by FastAPI at /)
COPY --from=frontend-build /ui/dist ./frontend/dist

# Pre-create directories that the app writes to at runtime.
# These are bind-mounted as volumes in docker-compose.yml so data persists.
RUN mkdir -p uploads outputs/structured outputs/raw_ocr

# Default command: run the FastAPI server
# The worker service overrides this CMD in docker-compose.yml
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
