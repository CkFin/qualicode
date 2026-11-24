"""POLITICA DE ARCHIVOS - QualiCode.

Se aceptan solo archivos de TEXTO con metricas de calidad o bitacoras de revision:

  * Extensiones permitidas: .csv y .txt
  * Tamano maximo: MAX_UPLOAD_BYTES (2 MiB por defecto); archivos vacios rechazados
  * Codificacion: UTF-8, sin bytes nulos (descarta binarios)
  * Firma (magic bytes): se rechazan ejecutables, PDF, ZIP/Office e imagenes
    aunque se renombren a .csv/.txt
  * CSV: debe tener encabezado con las columnas obligatorias
    modulo, fecha, cobertura, complejidad, defectos  y al menos una fila de datos

Motivo: el procesamiento solo interpreta texto; aceptar binarios aumenta la
superficie de ataque y el consumo de recursos sin aportar valor al negocio.
"""
import os
import re

ALLOWED_EXTENSIONS = {".csv": "csv", ".txt": "txt"}
CSV_REQUIRED_COLUMNS = ["modulo", "fecha", "cobertura", "complejidad", "defectos"]
CSV_MAX_ROWS = 50_000

# Firmas binarias conocidas que nunca deben entrar como "texto"
BINARY_SIGNATURES = {
    b"MZ": "ejecutable de Windows",
    b"\x7fELF": "ejecutable de Linux",
    b"%PDF": "documento PDF",
    b"PK\x03\x04": "archivo ZIP/Office",
    b"\x89PNG": "imagen PNG",
    b"\xff\xd8\xff": "imagen JPEG",
    b"GIF8": "imagen GIF",
}


class UploadRejected(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def safe_display_name(filename: str | None) -> str:
    """Nombre para mostrar: sin rutas ni caracteres de control. NUNCA se usa
    para construir rutas en disco (se usa el UUID del trabajo)."""
    name = os.path.basename((filename or "").replace("\\", "/"))
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    return name[:120] or "sin_nombre"


def validate_upload(filename: str | None, content: bytes, max_bytes: int) -> str:
    """Devuelve el tipo ('csv' o 'txt') o lanza UploadRejected con el motivo."""
    name = safe_display_name(filename)
    ext = os.path.splitext(name)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise UploadRejected(
            f"Tipo no permitido ('{ext or 'sin extension'}'). Solo se aceptan .csv y .txt", 415)
    if len(content) == 0:
        raise UploadRejected("El archivo esta vacio")
    if len(content) > max_bytes:
        raise UploadRejected(
            f"El archivo supera el maximo permitido de {max_bytes // 1024} KiB", 413)

    for signature, kind in BINARY_SIGNATURES.items():
        if content.startswith(signature):
            raise UploadRejected(f"El contenido es un {kind} disfrazado de {ext}", 415)
    if b"\x00" in content:
        raise UploadRejected("El archivo contiene bytes nulos: no es texto", 415)

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise UploadRejected("El archivo debe estar codificado en UTF-8")

    if ext == ".csv":
        _validate_csv(text)
    return ALLOWED_EXTENSIONS[ext]


def _validate_csv(text: str) -> None:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise UploadRejected("CSV sin contenido")
    header = [col.strip().lower() for col in lines[0].split(",")]
    missing = [c for c in CSV_REQUIRED_COLUMNS if c not in header]
    if missing:
        raise UploadRejected(
            "CSV con esquema invalido. Faltan columnas: " + ", ".join(missing)
            + ". Requeridas: " + ", ".join(CSV_REQUIRED_COLUMNS))
    if len(lines) < 2:
        raise UploadRejected("CSV sin filas de datos")
    if len(lines) - 1 > CSV_MAX_ROWS:
        raise UploadRejected(f"CSV con demasiadas filas (maximo {CSV_MAX_ROWS})")
