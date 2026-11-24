"""QualiCode - Trabajador de procesamiento asincrono.

Ciclo de vida de un trabajo:
    pendiente -> en_ejecucion -> completado | fallido

COLA: la tabla jobs de PostgreSQL. Cada trabajador reclama UN trabajo con
    SELECT ... FOR UPDATE SKIP LOCKED
de modo que varios trabajadores pueden correr en paralelo sin tomar el mismo
trabajo, y los trabajos pendientes sobreviven a cualquier reinicio.

RECUPERACION: al arrancar (y cada 30 s) los trabajos que quedaron
'en_ejecucion' por un trabajador caido vuelven a 'pendiente' (max 3 intentos).

APAGADO LIMPIO: SIGTERM (docker stop) termina el trabajo actual y sale.
"""
import json
import logging
import os
import signal
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from common import audit
from common.db import conninfo
from common.logs import setup_logging
from worker.processing.processors import ProcessingError, process_file, sha256_file

log = setup_logging("worker")
os.umask(0o027)

WORKER_ID = os.getenv("WORKER_ID") or socket.gethostname()
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "/data/storage"))
POLL_SECONDS = float(os.getenv("POLL_INTERVAL_SECONDS", "1"))
DELAY_SECONDS = float(os.getenv("PROCESSING_DELAY_SECONDS", "3"))  # hace visible "en_ejecucion"
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "3"))
HEARTBEAT_FILE = Path("/tmp/heartbeat")

running = True


def _stop(signum, _frame):
    global running
    running = False
    log.info("Senal %s recibida: se terminara el trabajo actual y se saldra", signal.Signals(signum).name)


signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)


def connect() -> psycopg.Connection:
    while True:
        try:
            conn = psycopg.connect(conninfo(), autocommit=True, row_factory=dict_row)
            log.info("Conectado a la base de datos")
            return conn
        except psycopg.OperationalError as exc:
            log.warning("BD no disponible (%s). Reintento en 3 s", str(exc).strip())
            time.sleep(3)


def heartbeat(conn, started: bool = False) -> None:
    if started:
        conn.execute(
            """INSERT INTO worker_heartbeat (worker_id, pid, started_at, last_seen)
               VALUES (%s, %s, now(), now())
               ON CONFLICT (worker_id) DO UPDATE
               SET pid = EXCLUDED.pid, started_at = now(), last_seen = now()""",
            (WORKER_ID, os.getpid()))
    else:
        conn.execute("UPDATE worker_heartbeat SET last_seen = now() WHERE worker_id = %s", (WORKER_ID,))
    HEARTBEAT_FILE.touch()


def recover_orphans(conn, at_startup: bool = False) -> None:
    """Devuelve a la cola los trabajos abandonados por un trabajador caido."""
    rows = conn.execute(
        """UPDATE jobs SET
               status = CASE WHEN attempts >= %(max)s THEN 'fallido' ELSE 'pendiente' END,
               error  = CASE WHEN attempts >= %(max)s
                             THEN 'Abortado: se alcanzo el maximo de intentos tras caidas del trabajador'
                             ELSE NULL END,
               finished_at = CASE WHEN attempts >= %(max)s THEN now() ELSE NULL END,
               worker_id = NULL, started_at = NULL
           WHERE status = 'en_ejecucion' AND (
                 (%(startup)s AND worker_id = %(me)s)
              OR worker_id NOT IN (SELECT worker_id FROM worker_heartbeat
                                   WHERE last_seen > now() - interval '30 seconds')
              OR started_at < now() - interval '10 minutes')
           RETURNING id, status""",
        {"max": MAX_ATTEMPTS, "me": WORKER_ID, "startup": at_startup}).fetchall()
    for row in rows:
        log.warning("RECUPERACION: trabajo %s huerfano -> %s", row["id"], row["status"])
        audit.record(conn, username=f"worker:{WORKER_ID}", role="sistema", action="TRABAJO_RECUPERADO",
                     resource=f"job:{row['id']}", outcome="OK", detail=f"nuevo estado {row['status']}")


def claim_job(conn) -> dict | None:
    return conn.execute(
        """UPDATE jobs SET status = 'en_ejecucion', started_at = now(),
                          attempts = attempts + 1, worker_id = %s
           WHERE id = (SELECT id FROM jobs WHERE status = 'pendiente'
                       ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)
           RETURNING id, owner_id, original_name, stored_path, file_type, sha256, attempts""",
        (WORKER_ID,)).fetchone()


def write_result(job: dict, result: dict) -> str:
    folder = STORAGE_DIR / "results" / str(int(job["owner_id"]))
    folder.mkdir(parents=True, exist_ok=True, mode=0o750)
    final = folder / f"{job['id']}.json"
    tmp = final.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o640)
    os.replace(tmp, final)
    return str(final)


def run_job(conn, job: dict) -> None:
    job_id = job["id"]
    log.info("INICIO trabajo %s | archivo=%s | intento=%d", job_id, job["original_name"], job["attempts"])
    start = time.monotonic()
    try:
        if sha256_file(job["stored_path"]) != job["sha256"].strip():
            raise ProcessingError("Integridad comprometida: el hash SHA-256 del original no coincide")
        if DELAY_SECONDS:
            time.sleep(DELAY_SECONDS)
        result = process_file(job["stored_path"], job["file_type"])
        duration_ms = int((time.monotonic() - start) * 1000)
        result["_metadatos"] = {
            "trabajo": str(job_id), "archivo": job["original_name"], "sha256_original": job["sha256"].strip(),
            "procesado_por": WORKER_ID, "duracion_ms": duration_ms,
            "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        path = write_result(job, result)
        conn.execute("""UPDATE jobs SET status = 'completado', result_path = %s, error = NULL,
                        finished_at = now() WHERE id = %s""", (path, job_id))
        conn.execute("UPDATE worker_heartbeat SET jobs_done = jobs_done + 1 WHERE worker_id = %s", (WORKER_ID,))
        audit.record(conn, username=f"worker:{WORKER_ID}", role="sistema", action="TRABAJO_COMPLETADO",
                     resource=f"job:{job_id}", outcome="OK", detail=f"{duration_ms} ms")
        log.info("FIN trabajo %s | completado en %d ms", job_id, duration_ms)
    except Exception as exc:  # incluye ProcessingError y errores inesperados
        expected = isinstance(exc, ProcessingError)
        message = str(exc) if expected else "Error interno del trabajador (ver worker.log)"
        if expected:
            log.error("FALLO trabajo %s | %s", job_id, exc)
        else:
            log.exception("FALLO INESPERADO trabajo %s", job_id)
        conn.execute("""UPDATE jobs SET status = 'fallido', error = %s, finished_at = now()
                        WHERE id = %s""", (message, job_id))
        conn.execute("UPDATE worker_heartbeat SET jobs_failed = jobs_failed + 1 WHERE worker_id = %s",
                     (WORKER_ID,))
        audit.record(conn, username=f"worker:{WORKER_ID}", role="sistema", action="TRABAJO_FALLIDO",
                     resource=f"job:{job_id}", outcome="ERROR", detail=message)


def main() -> None:
    log.info("Trabajador %s iniciado (pid=%d, uid=%d)", WORKER_ID, os.getpid(), os.getuid())
    conn = connect()
    heartbeat(conn, started=True)
    recover_orphans(conn, at_startup=True)
    last_beat = last_sweep = time.monotonic()

    while running:
        try:
            now = time.monotonic()
            if now - last_beat >= 5:
                heartbeat(conn)
                last_beat = now
            if now - last_sweep >= 30:
                recover_orphans(conn)
                last_sweep = now

            job = claim_job(conn)
            if job:
                run_job(conn, job)
            else:
                time.sleep(POLL_SECONDS)
        except psycopg.OperationalError as exc:
            log.error("Conexion con la BD perdida (%s). Reconectando...", str(exc).strip())
            try:
                conn.close()
            except Exception:
                pass
            conn = connect()
            heartbeat(conn, started=True)

    log.info("Trabajador %s detenido correctamente", WORKER_ID)
    conn.close()


if __name__ == "__main__":
    main()
