FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MADD_BIND_HOST=0.0.0.0 \
    MADD_PORT=8000 \
    MADD_PILOT_DATA_DIR=/data

RUN groupadd --system madd && useradd --system --gid madd --create-home madd

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir . && \
    mkdir -p /data /data-root && chown madd:madd /data /data-root

USER madd
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3).read()"]

CMD ["madd-pilot-api"]
