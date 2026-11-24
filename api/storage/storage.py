"""Almacenamiento persistente (volumen Docker "storage" montado en /data/storage).

Estructura - los datos de cada usuario quedan separados por carpeta:
    /data/storage/uploads/<id_usuario>/<id_trabajo>.<csv|txt>   originales
    /data/storage/results/<id_usuario>/<id_trabajo>.json        resultados

Permisos: carpetas 750 y archivos 640 (solo el usuario del servicio, uid 10001).
El nombre en disco es el UUID del trabajo: el nombre enviado por el usuario
nunca forma parte de la ruta (previene path traversal).
"""
import os
from pathlib import Path

from api.config import settings

os.umask(0o027)
BASE = Path(settings.STORAGE_DIR).resolve()


def user_dir(kind: str, owner_id: int) -> Path:
    if kind not in ("uploads", "results"):
        raise ValueError("tipo de carpeta invalido")
    path = BASE / kind / str(int(owner_id))
    path.mkdir(parents=True, exist_ok=True, mode=0o750)
    return path


def save_upload(owner_id: int, job_id, file_type: str, content: bytes) -> str:
    final = user_dir("uploads", owner_id) / f"{job_id}.{file_type}"
    tmp = final.with_suffix(final.suffix + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(tmp, 0o640)
    os.replace(tmp, final)  # escritura atomica: el worker nunca ve un archivo a medias
    return str(final)


def remove(path: str | None) -> None:
    if not path:
        return
    target = Path(path).resolve()
    if BASE not in target.parents:  # nunca borrar fuera del almacenamiento
        raise ValueError(f"Ruta fuera del almacenamiento: {target}")
    target.unlink(missing_ok=True)


def usage_bytes() -> dict:
    totals = {}
    for kind in ("uploads", "results"):
        root = BASE / kind
        totals[kind] = sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) if root.exists() else 0
    return totals
