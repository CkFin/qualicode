#!/usr/bin/env bash
# =====================================================================
#  Procedimiento de MANTENIMIENTO / ACTUALIZACIONES (requisito 2.3)
#
#  Los parches de seguridad se instalan solos (unattended-upgrades, H1).
#  Este script es el procedimiento SUPERVISADO para el resto de
#  actualizaciones (kernel, Docker, imagenes base), que pueden requerir
#  reinicio o reconstruir contenedores. Procedimiento del equipo:
#    1. Revisar estado y paquetes pendientes      (este script, sin argumentos)
#    2. Respaldar la base de datos                 (--aplicar lo hace)
#    3. Actualizar el sistema                      (--aplicar)
#    4. Reconstruir imagenes con parches de base   (--aplicar)
#    5. Verificar servicios y salud de la API
#
#  Uso: sudo bash infra/server/mantenimiento.sh            # solo reporte
#       sudo bash infra/server/mantenimiento.sh --aplicar  # reporte + actualizacion
# =====================================================================
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo "Ejecutar con sudo" >&2; exit 1; fi
cd /opt/qualicode
. /etc/os-release

echo "==== Estado del sistema ===="
echo "SO:            $PRETTY_NAME"
echo "Kernel:        $(uname -r)"
echo "Encendido:     $(uptime -p)"
echo "Ultimo apt:    $(stat -c %y /var/lib/apt/lists/partial 2>/dev/null | cut -d. -f1)"
apt-get update -qq
PENDING=$(apt list --upgradable 2>/dev/null | grep -c upgradable || true)
echo "Paquetes pendientes de actualizar: $PENDING"
apt list --upgradable 2>/dev/null | grep -E "openssh|openssl|linux-image|docker|sudo|libc6" || echo "  (ninguno critico)"
[[ -f /var/run/reboot-required ]] && echo "** Se requiere reiniciar el sistema **"
echo
echo "Imagenes base de los contenedores:"
docker images --format '  {{.Repository}}:{{.Tag}}  creada {{.CreatedSince}}' | grep -E "qualicode|python|postgres|nginx" || true

if [[ "${1:-}" != "--aplicar" ]]; then
  echo; echo "Para aplicar: sudo bash infra/server/mantenimiento.sh --aplicar"
  exit 0
fi

echo; echo "==== 1. Respaldo de la base de datos ===="
mkdir -p /var/backups/qualicode && chmod 700 /var/backups/qualicode
BK="/var/backups/qualicode/qualicode_$(date +%Y%m%d_%H%M%S).sql.gz"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$BK"
chmod 600 "$BK"; echo "Respaldo: $BK ($(du -h "$BK" | cut -f1))"

echo; echo "==== 2. Actualizacion del sistema ===="
DEBIAN_FRONTEND=noninteractive apt-get full-upgrade -y
apt-get autoremove -y

echo; echo "==== 3. Reconstruir imagenes con las ultimas imagenes base ===="
docker compose build --pull
docker compose up -d

echo; echo "==== 4. Verificacion ===="
sleep 10
docker compose ps
curl -fsS http://localhost/api/health && echo
[[ -f /var/run/reboot-required ]] && echo "Reinicie el sistema en una ventana de mantenimiento: sudo reboot"
echo "Mantenimiento finalizado $(date)" | tee -a /var/log/qualicode-mantenimiento.log
