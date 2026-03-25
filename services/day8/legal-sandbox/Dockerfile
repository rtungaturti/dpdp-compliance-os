FROM python:3.11-slim

RUN groupadd --gid 1001 appuser && \
    useradd --uid 1001 --gid appuser --shell /bin/bash --create-home appuser && \
    apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.base.txt /tmp/base.txt
RUN pip install --no-cache-dir -r /tmp/base.txt

COPY . .
RUN pip install --no-cache-dir -r requirements.txt 2>/dev/null || true

USER appuser
ENV PORT=8707
EXPOSE 8707

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8707/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8707", "--workers", "1"]
