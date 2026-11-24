"""Tokens de sesion JWT firmados con HS256.

El token viaja en una cookie HttpOnly + SameSite=Strict: JavaScript no puede
leerlo (mitiga XSS) y el navegador no lo envia desde otros sitios (mitiga CSRF).
Incluye 'ver' (token_version del usuario): al cerrar sesion, cambiar rol o
contrasena se incrementa y todos los tokens anteriores quedan invalidos.
"""
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from api.config import settings

ALGORITHM = "HS256"


def create_token(user: dict) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user["id"]),
        "ver": user["token_version"],
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_TTL_MIN),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Lanza jwt.PyJWTError si la firma es invalida o el token expiro."""
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM],
                      options={"require": ["sub", "exp", "ver"]})
