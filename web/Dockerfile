# Dockerfile for Web UI — Cloud Run Deployment

FROM python:3.11-slim

# Install system dependencies for WeasyPrint
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements (web-specific)
COPY web/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy web application
COPY web/ /app/

# Copy agent code (web UI needs access to agent modules for invocation)
COPY data_analyst_agent/ /app/data_analyst_agent/
COPY config/ /app/config/

# Set Python path
ENV PYTHONPATH="/app:${PYTHONPATH}"

# Create output directories
RUN mkdir -p /app/outputs /app/static/results

# Non-root user
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

# Expose port (Cloud Run uses PORT env var)
ENV PORT=8080
EXPOSE 8080

# Run web server
CMD exec gunicorn --bind :$PORT --workers 4 --worker-class uvicorn.workers.UvicornWorker --timeout 600 app:app
