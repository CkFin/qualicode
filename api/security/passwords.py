"""Contrasenas: hash Argon2id (argon2-cffi, ganador de la Password Hashing
Competition). Nunca se guardan ni registran en texto plano."""
import re

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()  # Argon2id con parametros recomendados por la libreria

# Hash ficticio: si el usuario no existe se verifica contra este hash para que
# el tiempo de respuesta sea similar (evita enumerar usuarios por tiempo).
DUMMY_HASH = _hasher.hash("usuario-inexistente-QualiCode-2026")


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(hashed: str, plain: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except (VerificationError, InvalidHashError):
        return False


def check_policy(password: str, username: str = "") -> str | None:
    """Politica de contrasenas. Devuelve el motivo del rechazo o None si es valida."""
    if len(password) < 10:
        return "La contrasena debe tener al menos 10 caracteres"
    if len(password) > 128:
        return "La contrasena no puede superar 128 caracteres"
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "La contrasena debe combinar letras y numeros"
    if username and username.lower() in password.lower():
        return "La contrasena no puede contener el nombre de usuario"
    return None
