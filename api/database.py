"""Pool de conexiones de la API y funciones de acceso a datos.

Todas las consultas usan parametros (%s): nunca se concatena texto del
usuario en el SQL (previene inyeccion SQL).
"""
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from common import audit as _audit
from common.db import conninfo

pool = ConnectionPool(
    conninfo(), min_size=1, max_size=8, open=False,
    kwargs={"autocommit": True, "row_factory": dict_row},
)


def open_pool() -> None:
    pool.open(wait=True, timeout=60)


def close_pool() -> None:
    pool.close()


def query(sql: str, params=None) -> list[dict]:
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchall()


def query_one(sql: str, params=None) -> dict | None:
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchone()


def execute(sql: str, params=None) -> int:
    with pool.connection() as conn:
        return conn.execute(sql, params).rowcount


def audit_event(**kwargs) -> None:
    """Atajo para registrar un evento de auditoria (ver common/audit.py)."""
    with pool.connection() as conn:
        _audit.record(conn, **kwargs)
