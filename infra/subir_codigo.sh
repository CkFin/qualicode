#!/usr/bin/env bash
# Empaqueta el proyecto (SIN secretos) y lo copia al servidor en /opt/qualicode.
# Se ejecuta desde Windows (Git Bash) o Linux.
#
# Uso: bash infra/subir_codigo.sh ubuntu@<IP_PUBLICA> 22 ~/.ssh/qualicode-key.pem
set -euo pipefail

DEST="${1:?Uso: subir_codigo.sh usuario@host [puerto] [llave.pem]}"
PORT="${2:-22}"
KEY="${3:-}"
SSH_OPTS=(-p "$PORT" -o StrictHostKeyChecking=accept-new)
SCP_OPTS=(-P "$PORT" -o StrictHostKeyChecking=accept-new)
if [[ -n "$KEY" ]]; then SSH_OPTS+=(-i "$KEY"); SCP_OPTS+=(-i "$KEY"); fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PKG="$(mktemp -d)/qualicode.tar.gz"

echo "==> Empaquetando (excluye .env, llaves y archivos locales)"
tar -C "$ROOT" -czf "$PKG" \
    --exclude='.env' --exclude='*.pem' --exclude='.git' --exclude='.qodo' \
    --exclude='__pycache__' --exclude='tests/resultados' --exclude='infra/aws/estado.env' \
    --exclude='~$*' --exclude='*.pptx' --exclude='*.docx' \
    .

echo "==> Copiando a $DEST"
scp "${SCP_OPTS[@]}" "$PKG" "$DEST:/tmp/qualicode.tar.gz"

echo "==> Extrayendo en /opt/qualicode (conserva .env existente)"
ssh "${SSH_OPTS[@]}" "$DEST" 'set -e
  sudo mkdir -p /opt/qualicode
  sudo tar -xzf /tmp/qualicode.tar.gz -C /opt/qualicode --no-same-owner
  rm -f /tmp/qualicode.tar.gz
  sudo find /opt/qualicode -name "*.sh" -exec sed -i "s/\r$//" {} +
  sudo chown -R root:$(id -gn) /opt/qualicode
  sudo chmod 750 /opt/qualicode
  [ -f /opt/qualicode/.env ] && sudo chown root:root /opt/qualicode/.env && sudo chmod 600 /opt/qualicode/.env
  ls -la /opt/qualicode'
echo "Listo."
