#!/usr/bin/env bash
# Genera /opt/qualicode/.env con secretos aleatorios (una sola vez).
# Uso: sudo bash infra/server/generar_env.sh [entorno]   (entorno: aws | local)
set -euo pipefail
APP_DIR=/opt/qualicode
ENV_FILE="$APP_DIR/.env"
DEPLOY_ENV="${1:-aws}"

if [[ $EUID -ne 0 ]]; then echo "Ejecutar con sudo" >&2; exit 1; fi
if [[ -f "$ENV_FILE" ]]; then
  echo ".env ya existe; no se sobrescribe (borrelo manualmente si desea regenerarlo)."
  exit 0
fi

rnd() { openssl rand -hex "$1"; }
ADMIN_PASS="Adm$(rnd 6)9"

umask 077
cat > "$ENV_FILE" <<EOF
DEPLOY_ENV=${DEPLOY_ENV}
HTTP_PORT=80
POSTGRES_DB=qualicode
POSTGRES_USER=qualicode_owner
POSTGRES_PASSWORD=$(rnd 24)
APP_DB_USER=qualicode_app
APP_DB_PASSWORD=$(rnd 24)
JWT_SECRET=$(rnd 32)
JWT_TTL_MIN=30
COOKIE_SECURE=false
ADMIN_USERNAME=admin
ADMIN_PASSWORD=${ADMIN_PASS}
MAX_UPLOAD_BYTES=2097152
MAX_ACTIVE_JOBS_PER_USER=5
PROCESSING_DELAY_SECONDS=3
EOF
chown root:root "$ENV_FILE"
chmod 600 "$ENV_FILE"

echo "Archivo $ENV_FILE creado (permisos 600, propietario root)."
echo "-----------------------------------------------------------"
echo " Contrasena inicial del usuario 'admin': ${ADMIN_PASS}"
echo " Guardela en un lugar seguro. No la publique en capturas."
echo "-----------------------------------------------------------"
