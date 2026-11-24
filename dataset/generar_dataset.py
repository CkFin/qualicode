"""Genera la CARGA DE PRUEBA PROPIA de QualiCode (datos 100 % sinteticos).

Determinista (semilla fija 2026): siempre produce los mismos archivos.
Uso:  python3 dataset/generar_dataset.py

Cada modulo se define con su lenguaje y metricas medias realistas de un pipeline
de integracion continua, de modo que el informe produzca casos reconocibles:
cobertura insuficiente (pruebas), complejidad alta (refactorizacion), demasiados
defectos (correccion), cobertura en descenso (monitoreo) y un modulo critico.
"""
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).parent
rng = random.Random(2026)
HEADER = "modulo,lenguaje,fecha,cobertura,complejidad,defectos\n"


def mediciones(modulos: dict, dias: int, por_dia: int, inicio=date(2026, 8, 1)) -> str:
    """modulos = {nombre: (lenguaje, cobertura_media, complejidad_media, defectos_media[, deriva_cobertura_por_dia])}"""
    filas = [HEADER]
    for d in range(dias):
        fecha = (inicio + timedelta(days=d)).isoformat()
        for nombre, (lenguaje, cob, cx, de, *deriva) in modulos.items():
            cob_dia = cob + (deriva[0] if deriva else 0) * d
            for _ in range(por_dia):
                filas.append(f"{nombre},{lenguaje},{fecha},{min(100, max(0, rng.gauss(cob_dia, 2))):.1f},"
                             f"{max(1, rng.gauss(cx, 1)):.1f},{max(0, rng.gauss(de, 1)):.1f}\n")
    return "".join(filas)


def escribir(nombre: str, contenido, modo="w"):
    ruta = OUT / nombre
    if modo == "wb":
        ruta.write_bytes(contenido)
    else:
        ruta.write_text(contenido, encoding="utf-8", newline="\n")
    print(f"{nombre:<34} {ruta.stat().st_size:>10,} bytes")


# 1. Repositorio pequeno (tienda web): WEB-02 con cobertura insuficiente -> pruebas
escribir("01_repo_tienda_web.csv", mediciones(
    {"WEB-01": ("javascript", 84, 8, 3), "WEB-02": ("javascript", 56, 10, 4), "WEB-03": ("python", 86, 7, 2)},
    dias=10, por_dia=2))

# 2. Repositorio mediano (app de pagos): complejidad, cobertura en descenso, modulo critico y defectos
escribir("02_repo_app_pagos.csv", mediciones(
    {"PAY-A": ("java", 79, 24, 4), "PAY-B": ("python", 74, 8, 3, -0.45),
     "PAY-C": ("go", 34, 9, 7), "PAY-D": ("csharp", 81, 11, 11)},
    dias=30, por_dia=3))

# 3. Bitacora de revision de codigo: los errores se concentran en PAY-C (el modulo sin pruebas)
notas = []
generales = ["Code review aprobado sin observaciones en el modulo {p}",
             "Se agregaron pruebas unitarias al modulo {p}",
             "Refactor de funciones duplicadas en el modulo {p}",
             "Se actualizo la documentacion del modulo {p}",
             "Consulta lenta detectada en el modulo {p}",
             "Merge de la rama de funcionalidades en el modulo {p}"]
for d in range(60):
    dia = (date(2026, 8, 1) + timedelta(days=d)).isoformat()
    modulo = rng.choice(["WEB-01", "WEB-02", "WEB-03", "PAY-A", "PAY-C", "PAY-D"])
    if modulo == "PAY-C" and rng.random() < 0.6:
        texto = f"Se reporta error de excepcion nula en produccion en el modulo {modulo}, {rng.randint(3, 40)} usuarios afectados"
    elif modulo == "WEB-02" and rng.random() < 0.4:
        texto = f"Se detecta vulnerabilidad XSS en un formulario del modulo {modulo}"
    else:
        texto = rng.choice(generales).format(p=modulo)
    notas.append(f"[{dia}] {texto}. Build de {rng.uniform(3, 12):.1f} min, "
                 f"{rng.choice(['exitoso', 'exitoso', 'exitoso', 'fallido'])}.")
escribir("03_bitacora_revision.txt",
         "BITACORA DE REVISION DE CODIGO - EQUIPO FICTICIO DE DESARROLLO\n\n" + "\n".join(notas) + "\n")

# 4. Archivo grande de metricas de CI (~1.3 MiB): prueba de rendimiento
lenguajes = ["python", "javascript", "java", "go", "csharp", "php"]
escribir("04_metricas_ci_grande.csv", mediciones(
    {f"MOD-{i:02d}": (lenguajes[i % len(lenguajes)], rng.uniform(30, 95), rng.uniform(5, 30), rng.uniform(1, 20))
     for i in range(1, 21)},
    dias=90, por_dia=19))

# 5. CSV con esquema valido pero datos corruptos: el trabajo termina FALLIDO
corrupto = mediciones({"CX-01": ("python", 75, 8, 3)}, dias=5, por_dia=3).splitlines(keepends=True)
corrupto.insert(9, "CX-01,python,2026-08-04,N/A,8.1,3.0\n")
escribir("05_metricas_corruptas.csv", "".join(corrupto))

# --- Archivos que la politica debe RECHAZAR en la carga ---
# 6. Esquema incorrecto (faltan columnas)
escribir("06_columnas_incorrectas.csv", "archivo,linea,estilo\nmain.py,10,ok\nutil.py,22,ok\n")
# 7. Ejecutable (extension no permitida)
escribir("07_instalador.exe", b"MZ\x90\x00\x03" + bytes(rng.randrange(256) for _ in range(2048)), "wb")
# 8. PDF disfrazado de .txt (firma binaria)
escribir("08_pdf_disfrazado.txt", b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj << /Type /Catalog >> endobj\n", "wb")
# 9. Excede el tamano maximo (2.5 MiB)
grande = mediciones({"XL-01": ("python", 75, 8, 3), "XL-02": ("java", 70, 12, 4)}, dias=400, por_dia=90)
escribir("09_excede_tamano.csv", grande[: int(2.5 * 1024 * 1024)])
