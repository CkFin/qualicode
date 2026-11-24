"""Configuracion de la API, leida exclusivamente de variables de entorno."""
import os


def _bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "si")


class Settings:
    DEPLOY_ENV = os.getenv("DEPLOY_ENV", "local")

    # Sesiones
    JWT_SECRET = os.environ.get("JWT_SECRET", "")
    JWT_TTL_MIN = int(os.getenv("JWT_TTL_MIN", "30"))
    COOKIE_NAME = "qualicode_session"
    COOKIE_SECURE = _bool("COOKIE_SECURE")

    # Administrador inicial
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin").strip().lower()
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

    # Politica de archivos y recursos
    MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(2 * 1024 * 1024)))
    MAX_ACTIVE_JOBS_PER_USER = int(os.getenv("MAX_ACTIVE_JOBS_PER_USER", "5"))
    STORAGE_DIR = os.getenv("STORAGE_DIR", "/data/storage")

    # Proteccion contra fuerza bruta
    LOGIN_MAX_FAILS = int(os.getenv("LOGIN_MAX_FAILS", "5"))
    LOGIN_WINDOW_MIN = int(os.getenv("LOGIN_WINDOW_MIN", "15"))


settings = Settings()

if len(settings.JWT_SECRET) < 32:
    raise RuntimeError("JWT_SECRET debe existir y tener al menos 32 caracteres (ver .env.example)")
