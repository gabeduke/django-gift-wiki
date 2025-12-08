# syntax=docker/dockerfile:1.4
# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Set work directory
WORKDIR /app

# Install system dependencies with BuildKit cache mount
# This caches apt packages between builds, making subsequent builds much faster
# Using DEBIAN_FRONTEND=noninteractive to avoid interactive prompts
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    DEBIAN_FRONTEND=noninteractive apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Upgrade pip (this layer is cached unless pip version changes)
RUN pip install --upgrade pip

# Copy only requirements first (better layer caching)
COPY requirements.txt /app/

# Install Python dependencies with cache mount (BuildKit feature)
# This caches pip packages between builds
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Copy project files (this layer invalidates when code changes)
COPY . /app/

# Make entrypoint executable
RUN chmod +x /app/entrypoint.sh

# Run the application
ENTRYPOINT ["/app/entrypoint.sh"]
