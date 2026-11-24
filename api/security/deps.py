"""Dependencias de FastAPI para autenticacion y autorizacion en el SERVIDOR."""
import jwt
from fastapi import Depends, HTTPException, Request

from api import database as db
from api.config import settings
from api.security.permissions import has_perm
from api.security.tokens import decode_token


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "desconocida"


def get_current_user(request: Request) -> dict:
    """Valida la cookie de sesion y carga el usuario ACTUAL desde la BD.

    El rol no se toma del token sino de la BD: si un administrador cambia el
    rol o desactiva la cuenta, el efecto es inmediato.
    """
    token = request.cookies.get(settings.COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="No autenticado")
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Sesion invalida o expirada")

    user = db.query_one(
        "SELECT id, username, role, active, token_version FROM users WHERE id = %s",
        (int(payload["sub"]),),
    )
    if not user or not user["active"] or user["token_version"] != payload.get("ver"):
        raise HTTPException(status_code=401, detail="Sesion revocada o usuario inactivo")
    return user


def require_perm(perm: str):
    """Exige un permiso de la matriz (api/security/permissions.py)."""

    def checker(request: Request, user: dict = Depends(get_current_user)) -> dict:
        if not has_perm(user["role"], perm):
            db.audit_event(
                user=user, action="PERMISO_DENEGADO",
                resource=f"{request.method} {request.url.path}", outcome="DENEGADO",
                ip=client_ip(request), detail=f"falta el permiso {perm}",
            )
            raise HTTPException(status_code=403,
                                detail=f"Acceso denegado: tu rol '{user['role']}' no tiene el permiso '{perm}'")
        return user

    return checker
