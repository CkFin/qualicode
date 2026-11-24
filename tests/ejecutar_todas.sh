#!/usr/bin/env bash
# Ejecuta TODAS las pruebas en orden y deja las evidencias en tests/resultados/.
# Uso (en el servidor, dentro de /opt/qualicode):  sudo bash tests/ejecutar_todas.sh
set -uo pipefail
cd "$(dirname "$0")"

if [[ -z "${ADMIN_PASS:-}" ]]; then
  read -r -s -p "Contrasena del usuario admin: " ADMIN_PASS; echo
fi
export ADMIN_PASS QUALICODE_URL="${QUALICODE_URL:-http://localhost}"
mkdir -p resultados

echo "################ 1/3 PRUEBAS FUNCIONALES Y DE SEGURIDAD ################"
python3 pruebas_funcionales.py; F=$?

echo; echo "################ 2/3 PRUEBA DE CARGA (con muestreo de recursos) ################"
bash monitor_recursos.sh 90 > /dev/null 2>&1 &
MON=$!
python3 prueba_carga.py --jobs "${JOBS:-30}" --concurrency "${CONC:-6}"; C=$?
kill "$MON" 2>/dev/null; wait "$MON" 2>/dev/null

echo; echo "################ 3/3 RECUPERACION Y PERSISTENCIA ################"
python3 prueba_recuperacion.py; R=$?

echo; echo "======================= RESUMEN ======================="
echo "Funcionales:  $([[ $F -eq 0 ]] && echo OK || echo FALLAS)"
echo "Carga:        $([[ $C -eq 0 ]] && echo OK || echo FALLAS)"
echo "Recuperacion: $([[ $R -eq 0 ]] && echo OK || echo FALLAS)"
echo "Evidencias:"; ls -1 resultados/
