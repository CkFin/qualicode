"""Autenticacion: inicio/cierre de sesion con credenciales individuales."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from api import database as db
from api.config import settings
from api.security.deps import client_ip, get_current_user
from api.security.passwords import DUMMY_HASH, verify_password
from api.security.permissions import ROLES, perms_of
from api.security.tokens import create_token

log = logging.getLogger("api.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=30)
    password: str = Field(min_length=1, max_length=128)


def _profile(user: dict) -> dict:
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "role_label": ROLES.get(user["role"], user["role"]),
        "permissions": perms_of(user["role"]),
    }


def _failed_attempts(username: str) -> int:
    """Intentos fallidos recientes desde el ultimo inicio exitoso (anti fuerza bruta)."""
    row = db.query_one(
        """SELECT count(*) AS n FROM audit_log
           WHERE action = 'LOGIN' AND outcome = 'DENEGADO' AND username = %s
             AND ts > now() - make_interval(mins => %s)
             AND ts > COALESCE((SELECT max(ts) FROM audit_log
                                WHERE action = 'LOGIN' AND outcome = 'OK' AND username = %s),
                               '-infinity'::timestamptz)""",
        (username, settings.LOGIN_WINDOW_MIN, username),
    )
    return row["n"]


@router.post("/login")
def login(data: LoginIn, request: Request, response: Response):
    ip = client_ip(request)
    username = data.username.strip().lower()

    if _failed_attempts(username) >= settings.LOGIN_MAX_FAILS:
        db.audit_event(username=username, action="LOGIN_BLOQUEADO", outcome="DENEGADO", ip=ip,
                       detail=f"{settings.LOGIN_MAX_FAILS} intentos fallidos en {settings.LOGIN_WINDOW_MIN} min")
        log.warning("Login bloqueado temporalmente para '%s' desde %s", username, ip)
        raise HTTPException(429, f"Cuenta bloqueada temporalmente por intentos fallidos. "
                                 f"Intenta en {settings.LOGIN_WINDOW_MIN} minutos.")

    user = db.query_one(
        "SELECT id, username, password_hash, role, active, token_version FROM users WHERE username = %s",
        (username,),
    )
    # Siempre se verifica un hash (real o ficticio) para no revelar si el usuario existe
    valid = verify_password(user["password_hash"] if user else DUMMY_HASH, data.password)

    if not user or not valid or not user["active"]:
        reason = "usuario inexistente" if not user else ("cuenta inactiva" if valid else "contrasena incorrecta")
        db.audit_event(user_id=user["id"] if user else None, username=username,
                       role=user["role"] if user else None, action="LOGIN",
                       outcome="DENEGADO", ip=ip, detail=reason)
        log.warning("Login fallido para '%s' desde %s (%s)", username, ip, reason)
        raise HTTPException(401, "Usuario o contrasena incorrectos")

    token = create_token(user)
    response.set_cookie(
        key=settings.COOKIE_NAME, value=token, httponly=True, secure=settings.COOKIE_SECURE,
        samesite="strict", max_age=settings.JWT_TTL_MIN * 60, path="/",
    )
    db.audit_event(user=user, action="LOGIN", outcome="OK", ip=ip)
    log.info("Login correcto de '%s' (%s) desde %s", user["username"], user["role"], ip)
    return _profile(user)


@router.post("/logout")
def logout(request: Request, response: Response, user: dict = Depends(get_current_user)):
    # Incrementar token_version revoca TODAS las sesiones activas del usuario
    db.execute("UPDATE users SET token_version = token_version + 1 WHERE id = %s", (user["id"],))
    response.delete_cookie(settings.COOKIE_NAME, path="/")
    db.audit_event(user=user, action="LOGOUT", outcome="OK", ip=client_ip(request))
    return {"message": "Sesion cerrada"}


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return _profile(user)
