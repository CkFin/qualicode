"""QualiCode - API principal (FastAPI).

Proceso principal del contenedor "api". Corre como usuario no privilegiado
'qualicode' (uid 10001) detras del proxy nginx; no publica puertos al exterior.
"""
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from common.logs import setup_logging

log = setup_logging("api")

from api import database as db  # noqa: E402  (despues de configurar logs)
from api.config import settings  # noqa: E402
from api.routes import admin, auth, jobs  # noqa: E402
from api.security.passwords import hash_password  # noqa: E402


def ensure_initial_admin() -> None:
    """Crea el administrador inicial (desde .env) si aun no existe."""
    if not settings.ADMIN_PASSWORD:
        log.warning("ADMIN_PASSWORD vacio: no se crea administrador inicial")
        return
    created = db.query_one(
        """INSERT INTO users (username, password_hash, role) VALUES (%s, %s, 'admin')
           ON CONFLICT (username) DO NOTHING RETURNING id""",
        (settings.ADMIN_USERNAME, hash_password(settings.ADMIN_PASSWORD)),
    )
    if created:
        db.audit_event(username="sistema", role="sistema", action="USUARIO_CREADO",
                       resource=f"user:{settings.ADMIN_USERNAME}", detail="administrador inicial")
        log.info("Administrador inicial '%s' creado", settings.ADMIN_USERNAME)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.open_pool()
    ensure_initial_admin()
    log.info("API iniciada (entorno=%s)", settings.DEPLOY_ENV)
    yield
    log.info("API detenida")
    db.close_pool()


# Sin /docs ni /openapi.json en produccion: no exponer el mapa de la API
app = FastAPI(title="QualiCode API", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(admin.router)


@app.middleware("http")
async def access_log(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    if request.url.path != "/api/health":
        log.info("%s %s -> %s (%.0f ms) ip=%s", request.method, request.url.path,
                 response.status_code, (time.perf_counter() - start) * 1000,
                 request.client.host if request.client else "-")
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Error no controlado en %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Error interno. Consulte los logs."})


@app.get("/api/health")
def health():
    db.query_one("SELECT 1 AS ok")
    return {"status": "ok", "environment": settings.DEPLOY_ENV}
