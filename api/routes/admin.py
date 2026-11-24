"""Administracion: usuarios y roles, auditoria y estado del sistema."""
import logging
import os
import shutil
import socket

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api import database as db
from api.config import settings
from api.security.deps import client_ip, require_perm
from api.security.passwords import check_policy, hash_password
from api.security.permissions import PERMISSION_DESCRIPTIONS, PERMISSIONS, ROLES
from api.storage import storage

log = logging.getLogger("api.admin")
router = APIRouter(tags=["admin"])


class UserCreate(BaseModel):
    username: str = Field(pattern=r"^[a-z0-9_.-]{3,30}$")
    password: str = Field(min_length=1, max_length=128)
    role: str


class UserUpdate(BaseModel):
    role: str | None = None
    active: bool | None = None
    password: str | None = Field(default=None, max_length=128)


# ------------------------------------------------------------------ usuarios
@router.get("/api/admin/users")
def list_users(user: dict = Depends(require_perm("users:manage"))):
    return db.query("""SELECT u.id, u.username, u.role, u.active, u.created_at,
                              (SELECT max(ts) FROM audit_log a WHERE a.user_id = u.id
                                 AND a.action = 'LOGIN' AND a.outcome = 'OK') AS last_login,
                              (SELECT count(*) FROM jobs j WHERE j.owner_id = u.id) AS jobs
                       FROM users u ORDER BY u.id""")


@router.post("/api/admin/users", status_code=201)
def create_user(data: UserCreate, request: Request, user: dict = Depends(require_perm("users:manage"))):
    if data.role not in ROLES:
        raise HTTPException(422, f"Rol invalido. Opciones: {', '.join(ROLES)}")
    problem = check_policy(data.password, data.username)
    if problem:
        raise HTTPException(422, problem)
    if db.query_one("SELECT 1 FROM users WHERE username = %s", (data.username,)):
        raise HTTPException(409, "Ya existe un usuario con ese nombre")

    new = db.query_one(
        "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) RETURNING id, username, role, active",
        (data.username, hash_password(data.password), data.role),
    )
    db.audit_event(user=user, action="USUARIO_CREADO", resource=f"user:{data.username}", outcome="OK",
                   ip=client_ip(request), detail=f"rol {data.role}")
    log.info("Usuario '%s' (%s) creado por '%s'", data.username, data.role, user["username"])
    return new


@router.patch("/api/admin/users/{user_id}")
def update_user(user_id: int, data: UserUpdate, request: Request,
                user: dict = Depends(require_perm("users:manage"))):
    target = db.query_one("SELECT id, username, role, active FROM users WHERE id = %s", (user_id,))
    if not target:
        raise HTTPException(404, "Usuario no encontrado")
    if target["id"] == user["id"] and (data.active is False or (data.role and data.role != "admin")):
        raise HTTPException(409, "No puedes desactivarte ni quitarte el rol de administrador a ti mismo")

    changes = []
    if data.role is not None:
        if data.role not in ROLES:
            raise HTTPException(422, f"Rol invalido. Opciones: {', '.join(ROLES)}")
        db.execute("UPDATE users SET role = %s WHERE id = %s", (data.role, user_id))
        changes.append(f"rol {target['role']} -> {data.role}")
    if data.active is not None:
        db.execute("UPDATE users SET active = %s WHERE id = %s", (data.active, user_id))
        changes.append("activado" if data.active else "desactivado")
    if data.password:
        problem = check_policy(data.password, target["username"])
        if problem:
            raise HTTPException(422, problem)
        db.execute("UPDATE users SET password_hash = %s WHERE id = %s", (hash_password(data.password), user_id))
        changes.append("contrasena restablecida")
    if not changes:
        raise HTTPException(422, "No se indico ningun cambio")

    # Cualquier cambio de seguridad invalida las sesiones abiertas del usuario
    db.execute("UPDATE users SET token_version = token_version + 1 WHERE id = %s", (user_id,))
    db.audit_event(user=user, action="USUARIO_MODIFICADO", resource=f"user:{target['username']}",
                   outcome="OK", ip=client_ip(request), detail="; ".join(changes))
    return db.query_one("SELECT id, username, role, active FROM users WHERE id = %s", (user_id,))


@router.get("/api/admin/roles")
def roles(user: dict = Depends(require_perm("users:manage"))):
    return {
        "roles": ROLES,
        "permissions": PERMISSION_DESCRIPTIONS,
        "matrix": {role: sorted(perms) for role, perms in PERMISSIONS.items()},
    }


# ----------------------------------------------------------------- auditoria
@router.get("/api/admin/audit")
def audit_log(username: str | None = None, action: str | None = None, outcome: str | None = None,
              resource: str | None = None, limit: int = 200,
              user: dict = Depends(require_perm("audit:read"))):
    where, params = [], []
    for column, value in (("username", username), ("action", action), ("outcome", outcome),
                          ("resource", resource)):
        if value:
            where.append(f"{column} = %s")
            params.append(value.strip())
    sql = "SELECT id, ts, username, role, action, resource, outcome, ip, detail FROM audit_log"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY ts DESC, id DESC LIMIT %s"
    params.append(max(1, min(limit, 1000)))
    return db.query(sql, params)


@router.get("/api/admin/audit/report")
def audit_report(hours: int = 24, user: dict = Depends(require_perm("audit:read"))):
    """Reporte propio de QualiCode: actividad y accesos denegados por usuario."""
    hours = max(1, min(hours, 24 * 30))
    per_user = db.query(
        """SELECT COALESCE(username, '-') AS username, COALESCE(role, '-') AS role,
                  count(*) FILTER (WHERE action = 'LOGIN' AND outcome = 'OK')       AS logins,
                  count(*) FILTER (WHERE action = 'LOGIN' AND outcome = 'DENEGADO') AS logins_fallidos,
                  count(*) FILTER (WHERE action = 'CARGA')                          AS cargas,
                  count(*) FILTER (WHERE action = 'DESCARGA' AND outcome = 'OK')    AS descargas,
                  count(*) FILTER (WHERE action = 'LIBERACION' AND outcome = 'OK')  AS liberaciones,
                  count(*) FILTER (WHERE outcome = 'DENEGADO')                      AS denegados,
                  max(ts) AS ultima_actividad
           FROM audit_log WHERE ts > now() - make_interval(hours => %s)
           GROUP BY 1, 2 ORDER BY denegados DESC, ultima_actividad DESC""", (hours,))
    denied = db.query(
        """SELECT action, count(*) AS total FROM audit_log
           WHERE outcome = 'DENEGADO' AND ts > now() - make_interval(hours => %s)
           GROUP BY action ORDER BY total DESC""", (hours,))
    return {"hours": hours, "per_user": per_user, "denied_by_action": denied}


# ------------------------------------------------------------ estado sistema
def _read_cgroup(name: str) -> str | None:
    try:
        with open(f"/sys/fs/cgroup/{name}") as fh:
            return fh.read().strip()
    except OSError:
        return None


@router.get("/api/system/status")
def system_status(user: dict = Depends(require_perm("system:status"))):
    counts = {row["status"]: row["n"] for row in
              db.query("SELECT status, count(*) AS n FROM jobs GROUP BY status")}
    workers = db.query(
        """SELECT worker_id, pid, started_at, last_seen, jobs_done, jobs_failed,
                  (now() - last_seen) < interval '15 seconds' AS alive
           FROM worker_heartbeat ORDER BY last_seen DESC LIMIT 10""")
    perf = db.query_one(
        """SELECT count(*) AS n,
                  round(avg(extract(epoch FROM finished_at - started_at))::numeric, 2) AS avg_proc_s,
                  round(avg(extract(epoch FROM started_at - created_at))::numeric, 2)  AS avg_wait_s
           FROM jobs WHERE status IN ('completado', 'fallido') AND finished_at > now() - interval '1 hour'""")
    disk = shutil.disk_usage(settings.STORAGE_DIR)
    mem_current, mem_max = _read_cgroup("memory.current"), _read_cgroup("memory.max")
    return {
        "environment": settings.DEPLOY_ENV,
        "api": {
            "hostname": socket.gethostname(),
            "pid": os.getpid(),
            "uid": os.getuid(),
            "load_avg": os.getloadavg(),
            "cgroup_memory_current": int(mem_current) if mem_current and mem_current.isdigit() else None,
            "cgroup_memory_max": mem_max,
            "cgroup_cpu_max": _read_cgroup("cpu.max"),
        },
        "queue": {s: counts.get(s, 0) for s in ("pendiente", "en_ejecucion", "completado", "fallido")},
        "last_hour": perf,
        "workers": workers,
        "storage": {
            "disk_total": disk.total, "disk_used": disk.used, "disk_free": disk.free,
            **storage.usage_bytes(),
        },
        "users": db.query_one("SELECT count(*) AS n FROM users WHERE active")["n"],
    }
