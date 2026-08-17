FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    RIDE_WEB_MODE=public_demo \
    RIDE_WEB_HOST=0.0.0.0 \
    RIDE_UI_DEFAULT_LANGUAGE=en \
    PORT=8080

WORKDIR /app

RUN groupadd --system ride && useradd --system --gid ride --home-dir /app ride

COPY pyproject.toml README.md ./
COPY app ./app
COPY gunicorn.conf.py ./

RUN python -m pip install --no-cache-dir ".[deploy]"

USER ride
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8080') + '/healthz', timeout=2).read()"]

CMD ["gunicorn", "--config", "gunicorn.conf.py", "app.web.server:application"]
