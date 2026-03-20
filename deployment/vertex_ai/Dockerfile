# Dockerfile for Vertex AI Agent Engine Deployment
# Multi-stage build for optimized image size

# ============================================================================
# Stage 1: Builder — Install dependencies and compile wheels
# ============================================================================
FROM python:3.11-slim as builder

# Install system dependencies for compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ make \
    libpq-dev \
    libxml2-dev libxslt1-dev \
    zlib1g-dev \
    libjpeg-dev libpng-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements and install
COPY deployment/vertex_ai/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /tmp/requirements.txt

# ============================================================================
# Stage 2: Runtime — Minimal production image
# ============================================================================
FROM python:3.11-slim

# Install runtime system dependencies (WeasyPrint needs these)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libxml2 libxslt1.1 \
    libjpeg62-turbo libpng16-16 \
    libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy application code
COPY data_analyst_agent/ /app/data_analyst_agent/
COPY config/ /app/config/
COPY data/ /app/data/
COPY web/ /app/web/

# Create output directories
RUN mkdir -p /app/outputs /app/logs

# Set Python path
ENV PYTHONPATH="/app:${PYTHONPATH}"

# Non-root user for security
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

# Health check endpoint (assumes FastAPI server for A2A)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8080/health', timeout=5).raise_for_status()" || exit 1

# Default command (override in agent_config.yaml if needed)
CMD ["python", "-m", "data_analyst_agent"]

# Metadata
LABEL maintainer="ty-hayes-82"
LABEL description="Data Analyst Agent - ADK-based P&L variance analysis system"
LABEL version="1.0.0"
