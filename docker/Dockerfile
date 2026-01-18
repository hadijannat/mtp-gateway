# syntax=docker/dockerfile:1
# MTP Gateway Production Dockerfile
# Multi-stage build for minimal production image

ARG PYTHON_VERSION=3.11
ARG VERSION=0.0.0

# ============================================================
# Stage 1: Build stage with all dependencies
# ============================================================
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

ARG VERSION

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set version for hatch-vcs when no git history available
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${VERSION}

# Install Python dependencies
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir . && \
    # Clean up to reduce image size
    find /opt/venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true && \
    find /opt/venv -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true && \
    find /opt/venv -type d -name "test" -exec rm -rf {} + 2>/dev/null || true && \
    find /opt/venv -name "*.pyc" -delete 2>/dev/null || true && \
    find /opt/venv -name "*.pyo" -delete 2>/dev/null || true && \
    rm -rf /opt/venv/share/doc 2>/dev/null || true

# ============================================================
# Stage 2: Production runtime
# ============================================================
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

# Security: Run as non-root user
RUN groupadd --gid 1000 mtpgateway && \
    useradd --uid 1000 --gid 1000 --shell /bin/bash --create-home mtpgateway

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application source
WORKDIR /app
COPY src/ ./src/

# Set ownership
RUN chown -R mtpgateway:mtpgateway /app

# Switch to non-root user
USER mtpgateway

# Expose OPC UA server port
EXPOSE 4840

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import socket; s=socket.socket(); s.settimeout(5); s.connect(('localhost', 4840)); s.close()" || exit 1

# Default environment variables
ENV MTP_LOG_LEVEL=INFO \
    MTP_LOG_FORMAT=json \
    MTP_OPCUA_ENDPOINT=opc.tcp://0.0.0.0:4840

# Volume mount points
VOLUME ["/config", "/certs"]

# Entry point
ENTRYPOINT ["mtp-gateway"]
CMD ["run", "/config/config.yaml"]
