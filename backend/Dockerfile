FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app
RUN useradd -r -u 10001 spark && chown -R spark /app
USER spark
ENV PORT=8080
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8080\")}/healthz')"
# Hypercorn handles SIGTERM gracefully (Cloud Run sends SIGTERM before shutdown).
CMD ["sh", "-c", "hypercorn app.main:app --bind 0.0.0.0:${PORT} --graceful-timeout 20 --access-logfile -"]
