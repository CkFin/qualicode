"""Auditoria: registra QUIEN hizo QUE, CUANDO, DESDE DONDE y con que RESULTADO.

Cada evento se guarda en dos lugares:
  1. Tabla audit_log (inmutable por trigger; la app solo tiene INSERT).
  2. /data/logs/audit.log en formato JSON (una linea por evento).

Uso:
    audit.record(conn, user=user, action="DESCARGA", resource=f"job:{id}",
                 outcome="OK", ip=ip, detail="...")
"""
import json
import logging
import os
from datetime import datetime, timezone

from common.logs import LOG_DIR

_log = logging.getLogger("audit")
_file_logger = logging.getLogger("audit.file")
_file_logger.propagate = False


def _ensure_file_handler() -> None:
    if _file_logger.handlers:
        return
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        handler = logging.FileHandler(os.path.join(LOG_DIR, "audit.log"), encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        _file_logger.addHandler(handler)
        _file_logger.setLevel(logging.INFO)
    except OSError as exc:
        _log.warning("No se pudo abrir audit.log: %s", exc)


def record(conn, *, action: str, outcome: str = "OK", user: dict | None = None,
           user_id: int | None = None, username: str | None = None, role: str | None = None,
           resource: str | None = None, ip: str | None = None, detail: str | None = None) -> None:
    if user:
        user_id, username, role = user["id"], user["username"], user["role"]

    event = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "user_id": user_id, "username": username, "role": role,
        "action": action, "resource": resource, "outcome": outcome,
        "ip": ip, "detail": detail,
    }
    try:
        conn.execute(
            """INSERT INTO audit_log (user_id, username, role, action, resource, outcome, ip, detail)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (user_id, username, role, action, resource, outcome, ip, detail),
        )
    except Exception:  # la auditoria nunca debe tumbar la peticion, pero si dejar rastro
        _log.exception("Fallo al registrar evento de auditoria en BD: %s", event)

    _ensure_file_handler()
    _file_logger.info(json.dumps(event, ensure_ascii=False))
