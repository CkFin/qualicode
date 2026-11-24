# ---------------------------------------------------------------
# Imagen del trabajador. Sin puertos, sin Internet, sin root.
# ---------------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd --system --gid 10001 qualicode \
 && useradd --system --uid 10001 --gid qualicode --no-create-home --shell /usr/sbin/nologin qualicode

WORKDIR /app
COPY worker/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY common/ /app/common/
COPY worker/ /app/worker/
RUN chmod -R a+rX,go-w /app \
 && mkdir -p /data/storage/uploads /data/storage/results /data/logs \
 && chown -R qualicode:qualicode /data \
 && chmod -R 750 /data

USER qualicode

# Sano si el latido se actualizo en los ultimos 30 s
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import os,sys,time; sys.exit(0 if time.time() - os.path.getmtime('/tmp/heartbeat') < 30 else 1)"

CMD ["python", "-m", "worker.worker"]
