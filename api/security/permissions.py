"""MATRIZ DE PERMISOS POR ROL - QualiCode.

Este archivo es la UNICA fuente de verdad de la autorizacion. Cada endpoint
de la API exige un permiso con require_perm("..."); ocultar botones en la
interfaz es solo cosmetico.

Para conceder una operacion a un rol (reto 2), agregar el permiso al
conjunto de ese rol y reiniciar la API:
    docker compose up -d --build api
"""

ROLES = {
    "admin": "Administrador (TI)",
    "tecnico": "Revisor QA (Operador)",
    "productor": "Desarrollador (Usuario)",
}

# Descripcion de cada permiso (se muestra en la documentacion y la interfaz)
PERMISSION_DESCRIPTIONS = {
    "jobs:create": "Cargar archivos y solicitar su procesamiento",
    "jobs:read_own": "Consultar sus propios trabajos",
    "jobs:download_own": "Descargar resultados propios (si estan liberados)",
    "jobs:delete_own": "Eliminar sus propios trabajos",
    "jobs:read_all": "Consultar metadatos de trabajos de todos los usuarios",
    "jobs:download_any": "Descargar resultados de cualquier usuario (revision QA)",
    "jobs:release": "Liberar informes al desarrollador (regla de negocio)",
    "jobs:retry": "Reencolar trabajos fallidos",
    "jobs:delete_any": "Eliminar trabajos de cualquier usuario",
    "users:manage": "Crear usuarios, cambiar roles, activar/desactivar",
    "audit:read": "Consultar el registro de auditoria y reportes",
    "system:status": "Ver estado de servicios, cola y recursos",
}

PERMISSIONS: dict[str, set[str]] = {
    "productor": {
        "jobs:create",
        "jobs:read_own",
        "jobs:download_own",
        "jobs:delete_own",
    },
    "tecnico": {
        "jobs:create",
        "jobs:read_own",
        "jobs:download_own",
        "jobs:delete_own",
        "jobs:read_all",
        "jobs:download_any",
        "jobs:release",
        "jobs:retry",
        "system:status",
    },
    # Minimo privilegio: el administrador gestiona la plataforma pero NO lee
    # el contenido de los analisis de los productores (no tiene download_any).
    "admin": {
        "jobs:read_all",
        "jobs:delete_any",
        "users:manage",
        "audit:read",
        "system:status",
    },
}


def has_perm(role: str, perm: str) -> bool:
    return perm in PERMISSIONS.get(role, set())


def perms_of(role: str) -> list[str]:
    return sorted(PERMISSIONS.get(role, set()))
