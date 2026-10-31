FROM python:3.11-slim

WORKDIR /app

# 项目零第三方依赖，无需 pip install
COPY backend ./backend
COPY server.py .env.example ./

ENV HOST=0.0.0.0 \
    MOCK=0 \
    DAILY_LIMIT=60 \
    CACHE_TTL=3600 \
    RATE_LIMIT_PER_MIN=20 \
    MAX_BODY_BYTES=65536

EXPOSE 8010

HEALTHCHECK --interval=60s --timeout=5s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8010/api/health',timeout=3)" || exit 1

CMD ["python", "server.py", "8010"]
