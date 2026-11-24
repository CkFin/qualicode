# ---------------------------------------------------------------
# Imagen de la API. Se ejecuta como usuario NO privilegiado.
# Contexto de build: raiz del proyecto (copia common/ y api/).
# ---------------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Usuario de servicio sin shell ni home (mismo uid que el usuario 'qualicode' del host)
RUN groupadd --system --gid 10001 qualicode \
 && useradd --system --uid 10001 --gid qualicode --no-create-home --shell /usr/sbin/nologin qualicode

WORKDIR /app
COPY api/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt && rm /tmp/requirements.txt

# El codigo pertenece a root y es de solo lectura para la aplicacion
COPY common/ /app/common/
COPY api/ /app/api/
RUN chmod -R a+rX,go-w /app \
 && mkdir -p /data/storage/uploads /data/storage/results /data/logs \
 && chown -R qualicode:qualicode /data \
 && chmod -R 750 /data

USER qualicode
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log"]
