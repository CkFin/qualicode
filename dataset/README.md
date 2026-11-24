# Carga de prueba propia · QualiCode

Son 9 archivos **100 % sintéticos**, sin datos personales ni reales. Se generan de forma
determinista (semilla 2026) con:

```bash
python3 dataset/generar_dataset.py
```

| # | Archivo | Tipo | Tamaño | Contenido | Resultado esperado |
|---|---|---|---:|---|---|
| 1 | `01_repo_tienda_web.csv` | CSV | 2.4 KiB | Tienda web: 3 módulos × 10 días × 2 builds (60 filas) | **Completado**. WEB-02 en *atención* por cobertura 56 % → ≈ 25 pruebas por KLOC; WEB-01 y WEB-03 óptimos |
| 2 | `02_repo_app_pagos.csv` | CSV | 12.8 KiB | App de pagos: 4 módulos × 30 días × 3 builds (360 filas) | **Completado**. PAY-C (Go) *crítico*, cobertura 34 % → ≈ 47 pruebas/KLOC; PAY-A (Java) complejidad 24 → ≈ 14 h de refactorización; PAY-B cobertura en descenso; PAY-D 11 defectos/KLOC |
| 3 | `03_bitacora_revision.txt` | TXT | 5.8 KiB | 60 notas de code review con fecha, módulo y build | **Completado**. Alerta: errores repetidos en PAY-C; vulnerabilidad XSS en WEB-02; builds fallidos |
| 4 | `04_metricas_ci_grande.csv` | CSV | 1.26 MiB | 20 módulos × 90 días × 19 builds (34 200 filas), 6 lenguajes | **Completado**. Se usa en la prueba de rendimiento |
| 5 | `05_metricas_corruptas.csv` | CSV | 644 B | Esquema válido, fila 10 con `cobertura = N/A` | **Fallido**: "Fila 10: valor no numérico en 'cobertura'" |
| 6 | `06_columnas_incorrectas.csv` | CSV | 49 B | Encabezado `archivo,linea,estilo` | **Rechazado** en la carga (422: faltan columnas) |
| 7 | `07_instalador.exe` | binario | 2.0 KiB | Firma `MZ` de ejecutable | **Rechazado** (415: extensión no permitida) |
| 8 | `08_pdf_disfrazado.txt` | binario | 51 B | Firma `%PDF` con extensión .txt | **Rechazado** (415: PDF disfrazado) |
| 9 | `09_excede_tamano.csv` | CSV | 2.5 MiB | Supera el límite de 2 MiB | **Rechazado** (413: tamaño) |

## Qué produce el procesamiento

- **CSV:** un informe de calidad por módulo. Compara la complejidad con el umbral de su **lenguaje**
  (columna opcional `lenguaje`), clasifica la cobertura y la densidad de defectos, asigna un semáforo
  (óptimo, atención o crítico) y estima el esfuerzo: pruebas a escribir, horas de refactorización y
  defectos a corregir.
- **TXT:** clasifica las notas de revisión por categoría (seguridad, errores, rendimiento, pruebas,
  mantenibilidad), cuenta las incidencias por módulo, mide la duración de los builds y los fallidos, y
  alerta cuando un problema se repite.

El dataset cuenta una historia coherente: PAY-C (el módulo con menos pruebas) es también el que más
errores reporta en la bitácora.

## Política de archivos (resumen)

- Solo `.csv` y `.txt`, en UTF-8, de 1 byte a 2 MiB.
- Se rechazan firmas binarias (EXE, ELF, PDF, ZIP/Office, PNG, JPEG, GIF) y cualquier archivo con bytes nulos.
- El CSV debe contener las columnas `modulo, fecha, cobertura, complejidad, defectos` y como máximo 50 000 filas.
- En el procesamiento se validan los rangos: cobertura 0–100 %, complejidad 0–200, defectos 0–1000 por KLOC.

**Por qué:** el procesamiento solo interpreta texto. Aceptar binarios aumenta la superficie de ataque y
el consumo de recursos sin aportar valor al negocio.
