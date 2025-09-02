# syntax=docker/dockerfile:1

FROM --platform=linux/amd64 python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

ARG KUBECTL_VERSION=v1.30.4

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       ca-certificates curl bash \
    && update-ca-certificates \
    && curl -fsSLo /usr/local/bin/kubectl \
         https://storage.googleapis.com/kubernetes-release/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl \
    && chmod +x /usr/local/bin/kubectl \
    && kubectl version --client \
    && apt-get purge -y --auto-remove curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency manifests first for better caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY agent.py ./

# Non-root user
RUN useradd -u 1000 -m appuser \
    && chown -R appuser:appuser /app
USER appuser

# Default command
CMD ["python", "./agent.py"]