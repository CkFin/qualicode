#!/usr/bin/env bash
# =====================================================================
#  QualiCode - Preparacion y HARDENING del servidor Linux
#  Servidor: Ubuntu Server 24.04 LTS en AWS EC2
#
#  Uso:   sudo bash infra/server/hardening.sh [--allow-password-ssh]
#         --allow-password-ssh  permite SSH con contrasena (solo si aun no
#                               hay llave configurada; NO recomendado)
#
#  Medidas aplicadas (documentadas en docs/ARQUITECTURA.md y la sustentacion):
#   H1  Actualizaciones de seguridad automaticas + procedimiento de mantenimiento
#   H2  Usuario de servicio sin privilegios 'qualicode' (uid 10001, sin shell)
#   H3  SSH endurecido: sin root, solo llave, 3 intentos, sin X11/tuneles
#   H4  Firewall UFW: deny por defecto; solo 22 y 80 entrantes
#   H5  fail2ban contra fuerza bruta en SSH (backend systemd/journald)
#   H6  Servicios innecesarios deshabilitados
#   H7  Parametros del kernel (sysctl) endurecidos
#   H8  Docker: no-new-privileges global, logs rotados, live-restore
#   H9  Permisos restrictivos del proyecto (/opt/qualicode 750, .env 600)
# =====================================================================
set -euo pipefail

ALLOW_PASSWORD_SSH=no
for arg in "$@"; do
  case "$arg" in
    --allow-password-ssh) ALLOW_PASSWORD_SSH=yes ;;
    *) echo "Opcion desconocida: $arg" >&2; exit 1 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then echo "Ejecutar con sudo" >&2; exit 1; fi

. /etc/os-release
APP_DIR=/opt/qualicode
ADMIN_USER="${SUDO_USER:-$(logname 2>/dev/null || echo ubuntu)}"
echo "Sistema detectado: $PRETTY_NAME | administrador: $ADMIN_USER"

step() { echo; echo "==== $* ===="; }

# ---------------------------------------------------------------- H1
step "H1 Paquetes y actualizaciones"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y
apt-get install -y docker.io docker-compose-v2 ufw fail2ban python3-systemd openssh-server \
                   unattended-upgrades htop sysstat tree curl ca-certificates openssl python3

# Parches de seguridad automaticos (diarios)
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
systemctl enable --now unattended-upgrades
docker compose version

# ---------------------------------------------------------------- H2
step "H2 Usuario de servicio 'qualicode' (uid 10001, sin login)"
if ! id qualicode &>/dev/null; then
  groupadd --system --gid 10001 qualicode
  useradd --system --uid 10001 --gid qualicode --no-create-home \
          --home-dir /nonexistent --shell /usr/sbin/nologin qualicode
fi
id qualicode
# Decision: el administrador NO se agrega al grupo 'docker' (equivale a root).
# Todo comando docker exige sudo y queda registrado en el journal (sudo).

# ---------------------------------------------------------------- H3
step "H3 Endureciendo SSH"
if [[ "$ALLOW_PASSWORD_SSH" == no ]] && [[ ! -s "$(getent passwd "$ADMIN_USER" | cut -d: -f6)/.ssh/authorized_keys" ]]; then
  echo "AVISO: $ADMIN_USER no tiene llave SSH en ~/.ssh/authorized_keys."
  echo "       Se deshabilitan las contrasenas igualmente: copie una llave antes de cerrar"
  echo "       esta sesion o use --allow-password-ssh."
fi
PASSWORD_AUTH=no
[[ "$ALLOW_PASSWORD_SSH" == yes ]] && PASSWORD_AUTH=yes
mkdir -p /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/99-qualicode.conf <<EOF
# QualiCode - acceso administrativo remoto permitido
PermitRootLogin no
PasswordAuthentication ${PASSWORD_AUTH}
KbdInteractiveAuthentication no
PubkeyAuthentication yes
PermitEmptyPasswords no
MaxAuthTries 3
LoginGraceTime 30
X11Forwarding no
AllowTcpForwarding no
ClientAliveInterval 300
ClientAliveCountMax 2
AllowUsers ${ADMIN_USER}
EOF
if [[ -f /etc/ssh/sshd_config.d/50-cloud-init.conf ]]; then
  sed -i "s/^PasswordAuthentication.*/PasswordAuthentication ${PASSWORD_AUTH}/" /etc/ssh/sshd_config.d/50-cloud-init.conf
fi
sshd -t   # valida la sintaxis ANTES de reiniciar (evita quedarse sin acceso)
systemctl enable ssh
systemctl restart ssh

# ---------------------------------------------------------------- H4
step "H4 Firewall UFW (solo 22/tcp y 80/tcp)"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw limit 22/tcp comment 'SSH administracion (con limite de tasa)'
ufw allow 80/tcp comment 'HTTP QualiCode (proxy nginx)'
ufw --force enable
systemctl enable ufw
ufw status verbose

# ---------------------------------------------------------------- H5
step "H5 fail2ban para SSH"
cat > /etc/fail2ban/jail.d/qualicode.conf <<'EOF'
[sshd]
enabled  = true
backend  = systemd
maxretry = 4
findtime = 10m
bantime  = 1h
EOF
systemctl enable fail2ban
systemctl restart fail2ban

# ---------------------------------------------------------------- H6
step "H6 Deshabilitando servicios innecesarios"
# Servicios que un servidor de aplicaciones en la nube no necesita. Un apache2/nginx
# o postgresql del host chocarian con los contenedores o expondrian otro servicio.
for svc in apache2.service nginx.service postgresql.service smbd.service nmbd.service \
           rpcbind.service rpcbind.socket ModemManager.service \
           multipathd.service multipathd.socket cups.service cups-browsed.service \
           avahi-daemon.service avahi-daemon.socket bluetooth.service; do
  if systemctl cat "$svc" &>/dev/null; then
    systemctl disable --now "$svc" &>/dev/null && echo "  deshabilitado: $svc" || true
  fi
done

# ---------------------------------------------------------------- H7
step "H7 Parametros del kernel"
cat > /etc/sysctl.d/99-qualicode.conf <<'EOF'
# Red: ignorar redirecciones y source routing, proteger contra SYN flood
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.all.log_martians = 1
net.ipv4.tcp_syncookies = 1
net.ipv4.icmp_echo_ignore_broadcasts = 1
# Kernel: ocultar punteros y dmesg a usuarios no privilegiados
kernel.kptr_restrict = 2
kernel.dmesg_restrict = 1
fs.protected_hardlinks = 1
fs.protected_symlinks = 1
# NOTA: net.ipv4.ip_forward se mantiene en 1 porque Docker lo necesita
EOF
sysctl --system >/dev/null

# ---------------------------------------------------------------- H8
step "H8 Configuracion segura del demonio Docker"
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
{
  "no-new-privileges": true,
  "live-restore": true,
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
EOF
systemctl enable docker
systemctl restart docker

# ---------------------------------------------------------------- H9
step "H9 Permisos del directorio de la aplicacion"
mkdir -p "$APP_DIR"
chown -R root:"$(id -gn "$ADMIN_USER")" "$APP_DIR"
chmod 750 "$APP_DIR"
[[ -f "$APP_DIR/.env" ]] && chown root:root "$APP_DIR/.env" && chmod 600 "$APP_DIR/.env"

step "RESUMEN"
echo "Puertos escuchando:"; ss -tulpn | grep LISTEN || true
echo
echo "Hardening completado en $PRETTY_NAME. Los comandos docker se ejecutan con sudo."
exit 0
