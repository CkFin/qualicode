#!/usr/bin/env bash
# Registra CPU / memoria de los contenedores y del host cada 2 s durante una prueba.
# Uso: sudo bash tests/monitor_recursos.sh [segundos]   (Ctrl+C para detener)
set -u
DURATION="${1:-120}"
OUT_DIR="$(dirname "$0")/resultados"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/recursos_$(date +%Y%m%d_%H%M%S).csv"

echo "fecha,contenedor,cpu,memoria,mem_pct,pids" > "$OUT"
END=$((SECONDS + DURATION))
while (( SECONDS < END )); do
  TS=$(date +%H:%M:%S)
  docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}},{{.PIDs}}' \
    | sed "s/^/${TS},/" | tee -a "$OUT"
  echo "--- host: $(uptime | sed 's/.*load average/load average/') | $(free -m | awk '/Mem:/{print "RAM usada " $3 "/" $2 " MiB"}')"
  sleep 2
done
echo "Muestras guardadas en $OUT"
