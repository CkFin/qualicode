#!/usr/bin/env bash
# Construye y (re)inicia la plataforma. Idempotente: se puede ejecutar varias veces.
# Uso: cd /opt/qualicode && sudo bash infra/server/deploy.sh
set -euo pipefail
cd /opt/qualicode

if [[ ! -f .env ]]; then
  echo "Falta .env. Ejecute primero: sudo bash infra/server/generar_env.sh" >&2
  exit 1
fi
chmod 600 .env

echo "==> Construyendo imagenes"
docker compose build

echo "==> Iniciando servicios"
docker compose up -d

echo "==> Esperando a que la API responda..."
for i in $(seq 1 30); do
  if curl -fsS http://localhost/api/health >/dev/null 2>&1; then
    echo "API disponible"; break
  fi
  sleep 2
done

docker compose ps
echo
IP=$(curl -fsS -m 2 -H "X-aws-ec2-metadata-token: $(curl -fsS -m 2 -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' 2>/dev/null)" \
     http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || hostname -I | awk '{print $1}')
echo "Plataforma disponible en: http://${IP}/"
