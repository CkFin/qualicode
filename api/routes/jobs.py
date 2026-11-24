"""Trabajos de procesamiento: carga, consulta, descarga, liberacion y eliminacion.

AISLAMIENTO ENTRE USUARIOS: toda consulta de un trabajo pasa por
_get_authorized_job(): si el trabajo no es del usuario y su rol no tiene
'jobs:read_all', se responde 404 (no se revela que el trabajo existe) y se
registra el intento en auditoria como ACCESO_AJENO.

REGLA DE NEGOCIO QualiCode ("liberacion tecnica"):
  1. Un productor solo puede descargar su resultado cuando un tecnico lo LIBERA.
  2. Segregacion de funciones: nadie puede liberar un trabajo que el mismo cargo.
"""
import hashlib
import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from api import database as db
from api.config import settings
from api.security.deps import client_ip, get_current_user, require_perm
from api.security.permissions import has_perm
from api.storage import storage
from api.validation.validator import UploadRejected, safe_display_name, validate_upload

log = logging.getLogger("api.jobs")
router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_COLUMNS = """j.id, j.owner_id, u.username AS owner, j.original_name, j.file_type, j.size_bytes,
              j.sha256, j.status, j.error, j.attempts, j.worker_id, j.released,
              r.username AS released_by, j.released_at, j.created_at, j.started_at, j.finished_at"""
_FROM = "FROM jobs j JOIN users u ON u.id = j.owner_id LEFT JOIN users r ON r.id = j.released_by"


def _public(job: dict) -> dict:
    return {k: v for k, v in job.items() if k not in ("stored_path", "result_path")}


def _load_job(job_id) -> dict | None:
    return db.query_one(f"SELECT {_COLUMNS}, j.stored_path, j.result_path {_FROM} WHERE j.id = %s",
                        (str(job_id),))


def _get_authorized_job(job_id, user: dict, request: Request, action: str) -> dict:
    job = _load_job(job_id)
    if job and (job["owner_id"] == user["id"] or has_perm(user["role"], "jobs:read_all")):
        return job
    if job:  # existe, pero pertenece a otro usuario
        db.audit_event(user=user, action="ACCESO_AJENO", resource=f"job:{job_id}", outcome="DENEGADO",
                       ip=client_ip(request), detail=f"intento de {action} sobre un trabajo de otro usuario")
        log.warning("ACCESO_AJENO: '%s' intento %s sobre job %s", user["username"], action, job_id)
    raise HTTPException(404, "Trabajo no encontrado")


def _deny(user: dict, request: Request, action: str, job_id, detail: str, status: int = 403):
    db.audit_event(user=user, action=action, resource=f"job:{job_id}", outcome="DENEGADO",
                   ip=client_ip(request), detail=detail)
    raise HTTPException(status, detail)


# --------------------------------------------------------------------- carga
@router.post("", status_code=201)
def upload(request: Request, file: UploadFile = File(...),
           user: dict = Depends(require_perm("jobs:create"))):
    ip = client_ip(request)
    name = safe_display_name(file.filename)
    content = file.file.read(settings.MAX_UPLOAD_BYTES + 1)

    try:
        file_type = validate_upload(name, content, settings.MAX_UPLOAD_BYTES)
    except UploadRejected as exc:
        db.audit_event(user=user, action="CARGA_RECHAZADA", resource=name, outcome="DENEGADO",
                       ip=ip, detail=str(exc))
        log.warning("Carga rechazada de '%s' (%s): %s", user["username"], name, exc)
        raise HTTPException(exc.status, str(exc))

    # Control de recursos: un productor no puede acaparar la cola
    if user["role"] == "productor":
        active = db.query_one(
            "SELECT count(*) AS n FROM jobs WHERE owner_id = %s AND status IN ('pendiente', 'en_ejecucion')",
            (user["id"],))["n"]
        if active >= settings.MAX_ACTIVE_JOBS_PER_USER:
            db.audit_event(user=user, action="CUOTA_EXCEDIDA", resource=name, outcome="DENEGADO", ip=ip,
                           detail=f"{active} trabajos activos (maximo {settings.MAX_ACTIVE_JOBS_PER_USER})")
            raise HTTPException(429, f"Tienes {active} trabajos en cola. Maximo permitido: "
                                     f"{settings.MAX_ACTIVE_JOBS_PER_USER}. Espera a que terminen.")

    job_id = uuid.uuid4()
    digest = hashlib.sha256(content).hexdigest()
    path = storage.save_upload(user["id"], job_id, file_type, content)
    db.execute(
        """INSERT INTO jobs (id, owner_id, original_name, stored_path, file_type, size_bytes, sha256)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (str(job_id), user["id"], name, path, file_type, len(content), digest),
    )
    db.audit_event(user=user, action="CARGA", resource=f"job:{job_id}", outcome="OK", ip=ip,
                   detail=f"{name} ({len(content)} bytes, sha256 {digest[:12]}...)")
    log.info("Trabajo %s encolado por '%s': %s (%d bytes)", job_id, user["username"], name, len(content))
    return _public(_load_job(job_id))


# ------------------------------------------------------------------ consulta
@router.get("")
def list_jobs(request: Request, scope: str = "mine", user: dict = Depends(get_current_user)):
    if scope == "all":
        if not has_perm(user["role"], "jobs:read_all"):
            _deny(user, request, "PERMISO_DENEGADO", "*", "Tu rol no puede ver trabajos de otros usuarios")
        return db.query(f"SELECT {_COLUMNS} {_FROM} ORDER BY j.created_at DESC LIMIT 500")
    if not has_perm(user["role"], "jobs:read_own"):
        raise HTTPException(403, "Tu rol no tiene trabajos propios")
    return db.query(f"SELECT {_COLUMNS} {_FROM} WHERE j.owner_id = %s ORDER BY j.created_at DESC LIMIT 200",
                    (user["id"],))


@router.get("/{job_id}")
def get_job(job_id: uuid.UUID, request: Request, user: dict = Depends(get_current_user)):
    return _public(_get_authorized_job(job_id, user, request, "consulta"))


# ------------------------------------------------------------------ descarga
@router.get("/{job_id}/result")
def download_result(job_id: uuid.UUID, request: Request, user: dict = Depends(get_current_user)):
    job = _get_authorized_job(job_id, user, request, "descarga")
    role = user["role"]
    is_owner = job["owner_id"] == user["id"]
    can_any = has_perm(role, "jobs:download_any")

    if not (can_any or (is_owner and has_perm(role, "jobs:download_own"))):
        _deny(user, request, "DESCARGA", job_id,
              "Tu rol no puede descargar el contenido de analisis de otros usuarios")
    if job["status"] != "completado" or not job["result_path"]:
        raise HTTPException(409, f"El trabajo esta '{job['status']}': aun no hay resultado")
    if not can_any and not job["released"]:
        _deny(user, request, "DESCARGA", job_id,
              "Regla QualiCode: el informe esta pendiente de liberacion por un revisor QA")

    db.audit_event(user=user, action="DESCARGA", resource=f"job:{job_id}", outcome="OK",
                   ip=client_ip(request), detail=f"resultado de {job['original_name']} (dueno: {job['owner']})")
    base = job["original_name"].rsplit(".", 1)[0]
    return FileResponse(job["result_path"], media_type="application/json",
                        filename=f"resultado_{base}.json")


# ------------------------------------------------- regla de negocio: liberar
@router.post("/{job_id}/release")
def release(job_id: uuid.UUID, request: Request, user: dict = Depends(require_perm("jobs:release"))):
    job = _get_authorized_job(job_id, user, request, "liberacion")
    if job["status"] != "completado":
        raise HTTPException(409, "Solo se pueden liberar trabajos completados")
    if job["released"]:
        raise HTTPException(409, f"El resultado ya fue liberado por {job['released_by']}")
    if job["owner_id"] == user["id"]:
        _deny(user, request, "LIBERACION", job_id,
              "Segregacion de funciones: no puedes liberar un analisis que tu mismo cargaste")

    db.execute("""UPDATE jobs SET released = TRUE, released_by = %s, released_at = now()
                  WHERE id = %s AND released = FALSE""", (user["id"], str(job_id)))
    db.audit_event(user=user, action="LIBERACION", resource=f"job:{job_id}", outcome="OK",
                   ip=client_ip(request), detail=f"resultado liberado al productor {job['owner']}")
    log.info("Trabajo %s liberado por '%s'", job_id, user["username"])
    return _public(_load_job(job_id))


@router.post("/{job_id}/retry")
def retry(job_id: uuid.UUID, request: Request, user: dict = Depends(require_perm("jobs:retry"))):
    job = _get_authorized_job(job_id, user, request, "reintento")
    if job["status"] != "fallido":
        raise HTTPException(409, "Solo se pueden reintentar trabajos fallidos")
    db.execute("""UPDATE jobs SET status = 'pendiente', error = NULL, started_at = NULL,
                  finished_at = NULL, worker_id = NULL WHERE id = %s""", (str(job_id),))
    db.audit_event(user=user, action="REINTENTO", resource=f"job:{job_id}", outcome="OK",
                   ip=client_ip(request))
    return _public(_load_job(job_id))


# ---------------------------------------------------------------- eliminar
@router.delete("/{job_id}")
def delete_job(job_id: uuid.UUID, request: Request, user: dict = Depends(get_current_user)):
    job = _get_authorized_job(job_id, user, request, "eliminacion")
    role = user["role"]
    is_owner = job["owner_id"] == user["id"]
    if not (has_perm(role, "jobs:delete_any") or (is_owner and has_perm(role, "jobs:delete_own"))):
        _deny(user, request, "ELIMINACION", job_id, "Tu rol no puede eliminar trabajos de otros usuarios")
    if job["status"] == "en_ejecucion":
        raise HTTPException(409, "No se puede eliminar un trabajo en ejecucion")

    storage.remove(job["stored_path"])
    storage.remove(job["result_path"])
    db.execute("DELETE FROM jobs WHERE id = %s", (str(job_id),))
    db.audit_event(user=user, action="ELIMINACION", resource=f"job:{job_id}", outcome="OK",
                   ip=client_ip(request), detail=f"{job['original_name']} (dueno: {job['owner']})")
    log.info("Trabajo %s eliminado por '%s'", job_id, user["username"])
    return {"message": "Trabajo eliminado"}
