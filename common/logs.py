"""Configuracion de logs: salida estandar (docker compose logs) + archivo rotativo.

Archivos en el volumen "logs":  /data/logs/api.log, /data/logs/worker.log,
/data/logs/audit.log (JSON por linea).
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

LOG_DIR = os.getenv("LOG_DIR", "/data/logs")


def setup_logging(service: str) -> logging.Logger:
    fmt = logging.Formatter(
        f"%(asctime)s %(levelname)-7s [{service}:%(process)d] %(message)s",
        "%Y-%m-%dT%H:%M:%S%z",
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        fh = RotatingFileHandler(
            os.path.join(LOG_DIR, f"{service}.log"),
            maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8",
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError as exc:  # p. ej. volumen sin permisos
        root.warning("No se pudo abrir el archivo de log: %s", exc)

    return logging.getLogger(service)
