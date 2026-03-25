FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy all service directories
COPY day1/ ./day1/
COPY day2/ ./day2/
COPY day6/ ./day6/
COPY day7/ ./day7/
COPY day8/ ./day8/
COPY combined/main.py ./combined/main.py

# Install base dependencies
RUN pip install --no-cache-dir \
    fastapi==0.111.0 \
    uvicorn[standard]==0.29.0 \
    pydantic==2.7.1 \
    pydantic-settings==2.2.1 \
    redis[asyncio]==5.0.4 \
    httpx==0.27.0 \
    structlog==24.1.0 \
    prometheus-client==0.20.0 \
    opentelemetry-sdk==1.24.0 \
    opentelemetry-instrumentation-fastapi==0.45b0 \
    opentelemetry-exporter-otlp==1.24.0

# Install each service's extra requirements
RUN for req in day1/*/requirements.txt day2/*/requirements.txt day6/*/requirements.txt day7/*/requirements.txt day8/*/requirements.txt; do \
    pip install --no-cache-dir -r $req 2>/dev/null || true; \
    done

WORKDIR /app/combined

ENV PORT=8000
ENV KAFKA_BOOTSTRAP=disabled
ENV OTEL_EXPORTER_OTLP_ENDPOINT=disabled

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

CMD ["sh", "-c", "uvicorn main:root --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
