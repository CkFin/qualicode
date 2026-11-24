"""Conexion a PostgreSQL compartida por la API y el trabajador.

Las credenciales llegan SOLO por variables de entorno (desde .env, que no
se versiona). Nunca se escriben en el codigo ni en la imagen Docker.
"""
import os

from psycopg.conninfo import make_conninfo


def conninfo() -> str:
    return make_conninfo(
        host=os.getenv("DB_HOST", "db"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        application_name=os.getenv("SERVICE_NAME", "qualicode"),
        connect_timeout="5",
    )
