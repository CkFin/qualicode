"""Procesamiento reproducible de archivos de QualiCode.

  * CSV de metricas de calidad -> INFORME DE CALIDAD por modulo:
      - estadisticas (min, max, promedio, desviacion) por metrica
      - interpretacion segun el umbral del LENGUAJE (columna opcional 'lenguaje')
      - semaforo por modulo: optimo / atencion / critico
      - recomendaciones con esfuerzo estimado: pruebas unitarias a escribir,
        horas de refactorizacion y defectos a corregir
      - tendencia de la cobertura en el periodo (primera vs. segunda mitad)
  * TXT de bitacora de revision de codigo -> eventos por categoria (seguridad,
      errores, rendimiento...), incidencias por modulo, builds y alertas.

Mismo archivo de entrada => mismo resultado (salvo marcas de tiempo).

Los umbrales son referencias generales de la industria simplificadas con fines
academicos. Por eso el informe sale como BORRADOR y un revisor QA debe
revisarlo y liberarlo (regla de negocio).
"""
import csv
import hashlib
import io
import math
import re
import statistics
import unicodedata
from collections import Counter, defaultdict

VARIABLES = ("cobertura", "complejidad", "defectos")
RANGES = {"cobertura": (0.0, 100.0), "complejidad": (0.0, 200.0), "defectos": (0.0, 1000.0)}

# ------------------------------------------------------- referencias de calidad
# Complejidad ciclomatica promedio maxima recomendada por lenguaje
LENGUAJES = {
    "python": ("Python", 10),
    "javascript": ("JavaScript", 12),
    "typescript": ("TypeScript", 12),
    "java": ("Java", 15),
    "go": ("Go", 12),
    "csharp": ("C#", 15),
    "c#": ("C#", 15),
    "php": ("PHP", 12),
    "general": ("Sin lenguaje declarado", 12),
}
COBERTURA_CRITICA = 40.0         # % de lineas cubiertas por pruebas
COBERTURA_MINIMA = 70.0
COBERTURA_OBJETIVO = 80.0
PRUEBAS_POR_PUNTO = 1.0          # pruebas unitarias por KLOC para subir 1 punto de cobertura
HORAS_POR_PUNTO_COMPLEJIDAD = 1.5
DEFECTOS_MAX = 5.0               # defectos por KLOC (analisis estatico)
DEFECTOS_CRITICO = 15.0
TENDENCIA_UMBRAL = 3.0           # puntos de cobertura entre mitades del periodo

ESTADO_ORDEN = {"critico": 0, "atencion": 1, "optimo": 2}


class ProcessingError(Exception):
    """Error esperado por contenido invalido: el trabajo termina como 'fallido'."""


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _plain(text: str) -> str:
    """Minusculas y sin tildes: 'Python ' -> 'python'."""
    norm = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(c for c in norm if not unicodedata.combining(c))


def _describe(values: list[float]) -> dict:
    return {
        "n": len(values),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "promedio": round(statistics.fmean(values), 2),
        "desv_estandar": round(statistics.pstdev(values), 2),
    }


# ------------------------------------------------------------ interpretacion
def _interpretar_cobertura(c: float) -> dict:
    if c < COBERTURA_CRITICA:
        nivel, texto = "critico", f"Cobertura muy baja (< {COBERTURA_CRITICA:g} %): cambios sin red de seguridad"
    elif c < COBERTURA_MINIMA:
        nivel, texto = "bajo", f"Cobertura insuficiente (< {COBERTURA_MINIMA:g} %)"
    else:
        nivel, texto = "optimo", f"Adecuada (≥ {COBERTURA_MINIMA:g} %)"
    return {"valor": round(c, 1), "nivel": nivel, "texto": texto, "optimo": [COBERTURA_MINIMA, 100]}


def _interpretar_complejidad(cx: float, lenguaje: str) -> dict:
    nombre, limite = LENGUAJES[lenguaje]
    if cx > limite * 2:
        nivel, texto = "critico", f"Complejidad muy alta: código difícil de probar (máx. {limite} en {nombre})"
    elif cx > limite:
        nivel, texto = "alto", f"Complejidad alta para {nombre} (máx. {limite})"
    else:
        nivel, texto = "optimo", f"Dentro del límite (≤ {limite})"
    return {"valor": round(cx, 1), "nivel": nivel, "texto": texto, "optimo": [0, limite]}


def _interpretar_defectos(d: float) -> dict:
    if d > DEFECTOS_CRITICO:
        nivel, texto = "critico", f"Densidad de defectos crítica (> {DEFECTOS_CRITICO:g} por KLOC)"
    elif d > DEFECTOS_MAX:
        nivel, texto = "alto", f"Demasiados defectos (> {DEFECTOS_MAX:g} por KLOC)"
    else:
        nivel, texto = "optimo", f"Aceptable (≤ {DEFECTOS_MAX:g} por KLOC)"
    return {"valor": round(d, 1), "nivel": nivel, "texto": texto, "optimo": [0, DEFECTOS_MAX]}


def _recomendaciones(cob: dict, cx: dict, de: dict, lenguaje: str, tendencia: dict) -> list[dict]:
    _, limite = LENGUAJES[lenguaje]
    recs = []
    if cob["nivel"] in ("bajo", "critico"):
        pruebas = math.ceil((COBERTURA_OBJETIVO - cob["valor"]) * PRUEBAS_POR_PUNTO)
        recs.append({"area": "Pruebas",
                     "accion": f"Escribir pruebas unitarias hasta llegar a {COBERTURA_OBJETIVO:g} % de cobertura. "
                               "Priorizar las funciones con más cambios recientes",
                     "dosis": f"≈ {pruebas} pruebas por KLOC"})
    if cx["nivel"] in ("alto", "critico"):
        horas = math.ceil((cx["valor"] - limite) * HORAS_POR_PUNTO_COMPLEJIDAD)
        recs.append({"area": "Refactorización",
                     "accion": "Dividir funciones largas (extraer métodos) y simplificar condicionales anidados",
                     "dosis": f"≈ {horas} h de refactorización"})
    if de["nivel"] in ("alto", "critico"):
        corregir = math.ceil(de["valor"] - DEFECTOS_MAX)
        recs.append({"area": "Corrección de defectos",
                     "accion": "Corregir los hallazgos del análisis estático, empezando por los de severidad alta",
                     "dosis": f"{corregir} defectos por KLOC"})
    if tendencia["direccion"] == "descendente":
        recs.append({"area": "Monitoreo",
                     "accion": f"La cobertura bajó {abs(tendencia['cambio'])} puntos en el periodo: exigir pruebas en cada pull request",
                     "dosis": "—"})
    return recs


def _tendencia(serie: list[tuple[str, float]]) -> dict:
    """Compara la cobertura promedio de la primera y la segunda mitad del periodo."""
    if len(serie) < 4:
        return {"direccion": "sin datos", "cambio": 0.0}
    ordenada = [v for _, v in sorted(serie, key=lambda x: x[0])]
    mitad = len(ordenada) // 2
    cambio = round(statistics.fmean(ordenada[mitad:]) - statistics.fmean(ordenada[:mitad]), 1)
    if cambio <= -TENDENCIA_UMBRAL:
        direccion = "descendente"
    elif cambio >= TENDENCIA_UMBRAL:
        direccion = "ascendente"
    else:
        direccion = "estable"
    return {"direccion": direccion, "cambio": cambio}


# --------------------------------------------------------------------- CSV
def process_csv(text: str) -> dict:
    reader = csv.DictReader(io.StringIO(text))
    reader.fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]

    values = {v: [] for v in VARIABLES}
    by_module = defaultdict(lambda: {v: [] for v in VARIABLES})
    langs = defaultdict(Counter)
    coverage_series = defaultdict(list)
    dates = []

    for line_no, row in enumerate(reader, start=2):
        if not any((cell or "").strip() for cell in row.values() if isinstance(cell, str)):
            continue
        module = (row.get("modulo") or "").strip() or "SIN_MODULO"
        date = (row.get("fecha") or "").strip()
        dates.append(date)
        langs[module][(row.get("lenguaje") or "").strip()] += 1   # nombre tal como lo escribio el desarrollador
        for var in VARIABLES:
            raw = (row.get(var) or "").strip()
            try:
                value = float(raw.replace(",", "."))
            except ValueError:
                raise ProcessingError(f"Fila {line_no}: valor no numerico en '{var}': {raw!r}")
            low, high = RANGES[var]
            if not low <= value <= high:
                raise ProcessingError(f"Fila {line_no}: '{var}' fuera de rango [{low}, {high}]: {value}")
            values[var].append(value)
            by_module[module][var].append(value)
        coverage_series[module].append((date, by_module[module]["cobertura"][-1]))

    if not values["cobertura"]:
        raise ProcessingError("El CSV no contiene filas de datos validas")

    modules = []
    for module, data in sorted(by_module.items()):
        declarado = langs[module].most_common(1)[0][0]
        lenguaje = _plain(declarado) if _plain(declarado) in LENGUAJES else "general"
        if lenguaje != "general" or not declarado:
            nombre_lenguaje = LENGUAJES[lenguaje][0]
        else:  # lenguaje sin umbral propio: se usa el general
            nombre_lenguaje = f"{declarado} (sin referencia: umbral general)"
        averages = {var: round(statistics.fmean(data[var]), 2) for var in VARIABLES}
        cob = _interpretar_cobertura(averages["cobertura"])
        cx = _interpretar_complejidad(averages["complejidad"], lenguaje)
        de = _interpretar_defectos(averages["defectos"])
        trend = _tendencia(coverage_series[module])
        niveles = [cob["nivel"], cx["nivel"], de["nivel"]]
        estado = "critico" if "critico" in niveles else ("atencion" if any(x != "optimo" for x in niveles) else "optimo")
        alerts = [i["texto"] for i in (cob, cx, de) if i["nivel"] != "optimo"]
        if trend["direccion"] == "descendente":
            alerts.append(f"Cobertura en descenso ({trend['cambio']} puntos en el periodo)")
        modules.append({
            "modulo": module,
            "lenguaje": nombre_lenguaje,
            "mediciones": len(data["cobertura"]),
            "estado": estado,
            "promedios": averages,
            "interpretacion": {"cobertura": cob, "complejidad": cx, "defectos": de},
            "tendencia_cobertura": trend,
            "variabilidad_complejidad": round(statistics.pstdev(data["complejidad"]), 2),
            "alertas": alerts,
            "recomendaciones": _recomendaciones(cob, cx, de, lenguaje, trend),
        })

    modules.sort(key=lambda m: (ESTADO_ORDEN[m["estado"]], m["modulo"]))
    resumen = Counter(m["estado"] for m in modules)
    prioridades = [f"{m['modulo']} ({m['lenguaje']}): " + "; ".join(r["area"].lower() + " " + r["dosis"]
                                                                    if r["dosis"] != "—" else r["area"].lower()
                                                                    for r in m["recomendaciones"])
                   for m in modules if m["estado"] != "optimo" and m["recomendaciones"]]
    valid_dates = sorted(d for d in dates if d)
    n_modules = len(modules)
    return {
        "tipo": "calidad_codigo",
        "filas": len(values["cobertura"]),
        "periodo": {"desde": valid_dates[0] if valid_dates else None,
                    "hasta": valid_dates[-1] if valid_dates else None},
        "estadisticas": {var: _describe(values[var]) for var in VARIABLES},
        "modulos": modules,
        "resumen": {"modulos": n_modules, "optimo": resumen["optimo"],
                    "atencion": resumen["atencion"], "critico": resumen["critico"]},
        "prioridades": prioridades,
        "diagnostico": (f"{resumen['critico']} críticos, {resumen['atencion']} requieren atención y "
                        f"{resumen['optimo']} en estado óptimo, de {n_modules} módulos"),
        "metodo": ("Promedio de mediciones por módulo comparado con el umbral de su lenguaje. "
                   "Esfuerzo estimado por cada 1 000 líneas de código (KLOC)."),
        "advertencia": ("Recomendaciones orientativas generadas automáticamente. "
                        "Requieren la revisión y liberación de un revisor QA."),
    }


# --------------------------------------------------------------------- TXT
CATEGORIAS = {
    "seguridad": ("vulnerabilidad", "inyeccion", "xss", "secreto", "credencial", "token", "csrf"),
    "errores": ("bug", "error", "excepcion", "fallo", "crash", "nulo"),
    "rendimiento": ("lento", "latencia", "memoria", "rendimiento", "timeout"),
    "pruebas": ("prueba", "pruebas", "test", "cobertura"),
    "mantenibilidad": ("refactor", "duplicado", "deuda", "estilo", "documentacion"),
}
RE_FECHA = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
RE_MODULO = re.compile(r"\b([A-Z]{2,4}-[A-Z0-9]{1,3})\b")   # API-01, WEB-02, PAY-D
RE_BUILD = re.compile(r"build\s+(?:de\s+)?(\d+(?:[.,]\d+)?)\s*min", re.IGNORECASE)


def process_txt(text: str) -> dict:
    words = re.findall(r"[^\W\d_]+", text, re.UNICODE)
    frequent = Counter(w.lower() for w in words if len(w) >= 5).most_common(10)
    lines = text.splitlines()

    eventos = Counter()
    por_modulo = defaultdict(lambda: {"menciones": 0, "seguridad": 0, "problemas": Counter()})
    incidencias, builds, fechas = [], [], []
    fallidos = set()
    for line in lines:
        if not line.strip():
            continue
        plain = _plain(line)
        tokens = set(re.findall(r"[a-z]+", plain))
        fecha = RE_FECHA.search(line)
        fecha = fecha.group(1) if fecha else None
        if fecha:
            fechas.append(fecha)
        modulos = RE_MODULO.findall(line)
        build = RE_BUILD.search(line)
        if build:
            builds.append(float(build.group(1).replace(",", ".")))
        if "fallido" in tokens and "build" in tokens:
            fallidos.add(fecha or line)
        cats = [c for c, kws in CATEGORIAS.items() if tokens & set(kws)]
        for c in cats:
            eventos[c] += 1
        for m in modulos:
            por_modulo[m]["menciones"] += 1
        if "seguridad" in cats or "errores" in cats:
            claves = CATEGORIAS["seguridad"] + CATEGORIAS["errores"]
            problema = next(k for k in claves if k in tokens)
            for m in modulos:
                por_modulo[m]["seguridad"] += 1
                por_modulo[m]["problemas"][problema] += 1
            incidencias.append({"fecha": fecha, "modulos": modulos, "problema": problema,
                                "nota": line.strip()[:160]})

    alertas = []
    modulos_out = []
    for m, d in sorted(por_modulo.items(), key=lambda x: (-x[1]["seguridad"], x[0])):
        principal = d["problemas"].most_common(1)[0] if d["problemas"] else None
        modulos_out.append({"modulo": m, "menciones": d["menciones"], "incidencias": d["seguridad"],
                            "problema_principal": principal[0] if principal else None})
        if principal and principal[1] >= 3:
            alertas.append(f"{m}: {principal[1]} reportes de {principal[0]}. "
                           "Programar revisión dedicada y plan de corrección")

    fechas.sort()
    return {
        "tipo": "bitacora_revision",
        "lineas": len(lines),
        "lineas_no_vacias": sum(1 for ln in lines if ln.strip()),
        "palabras": len(words),
        "caracteres": len(text),
        "periodo": {"desde": fechas[0] if fechas else None, "hasta": fechas[-1] if fechas else None},
        "notas": len(fechas),
        "eventos_por_categoria": dict(eventos.most_common()),
        "modulos": modulos_out,
        "incidencias": incidencias[-25:],   # las 25 mas recientes
        "builds": {"duracion_min": _describe(builds) if builds else None, "fallidos": len(fallidos)},
        "alertas": alertas,
        "palabras_frecuentes": [{"palabra": w, "veces": n} for w, n in frequent],
        "advertencia": "Resumen automático de la bitácora. El revisor QA valida las alertas antes de liberarlo.",
    }


def process_file(path: str, file_type: str) -> dict:
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ProcessingError("El archivo no esta en UTF-8")
    if file_type == "csv":
        return process_csv(text)
    if file_type == "txt":
        return process_txt(text)
    raise ProcessingError(f"Tipo de archivo no soportado: {file_type}")
