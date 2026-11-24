"""PRUEBAS FUNCIONALES Y DE SEGURIDAD - QualiCode.

Verifica de forma reproducible: autenticacion, roles, autorizacion en el
servidor, aislamiento entre usuarios, politica de archivos, ciclo del trabajo,
regla de negocio (liberacion tecnica + segregacion de funciones), auditoria y
revocacion de sesiones.

Uso (en el servidor):  ADMIN_PASS=... python3 tests/pruebas_funcionales.py
"""
import hashlib

from cliente import DATASET, Client, admin_client, ensure_user, save_results

results = []


def check(code: str, description: str, expected, obtained) -> bool:
    ok = obtained in expected if isinstance(expected, set) else obtained == expected
    results.append({"id": code, "prueba": description, "esperado": str(expected), "obtenido": str(obtained),
                    "resultado": "PASA" if ok else "FALLA"})
    print(f"[{'PASA' if ok else 'FALLA'}] {code} {description}  (esperado {expected}, obtenido {obtained})")
    return ok


def main():
    print("== Preparacion: usuarios de prueba ==")
    admin = admin_client()
    users = {name: ensure_user(admin, name, role)
             for name, role in (("prod_ana", "productor"), ("prod_beto", "productor"), ("tec_carla", "tecnico"))}
    ana, beto, carla = Client("ana"), Client("beto"), Client("carla")

    print("\n== Autenticacion ==")
    check("A1", "Login con contrasena incorrecta", 401, Client().login("prod_ana", "incorrecta123"))
    check("A2", "Login productor Ana", 200, ana.login("prod_ana", users["prod_ana"]))
    check("A3", "Login productor Beto", 200, beto.login("prod_beto", users["prod_beto"]))
    check("A4", "Login tecnico Carla", 200, carla.login("tec_carla", users["tec_carla"]))
    check("A5", "Peticion sin sesion", 401, Client().request("GET", "/api/jobs")[0])

    print("\n== Politica de archivos ==")
    check("V1", "Rechaza ejecutable .exe", 415, ana.upload("07_instalador.exe")[0])
    check("V2", "Rechaza PDF disfrazado de .txt", 415, ana.upload("08_pdf_disfrazado.txt")[0])
    check("V3", "Rechaza CSV con columnas incorrectas", 422, ana.upload("06_columnas_incorrectas.csv")[0])
    check("V4", "Rechaza archivo > 2 MiB", 413, ana.upload("09_excede_tamano.csv")[0])

    print("\n== Procesamiento asincrono ==")
    status, job, _ = ana.upload("01_repo_tienda_web.csv")
    check("P1", "Carga valida queda 'pendiente' (respuesta inmediata)", (201, "pendiente"), (status, job.get("status")))
    job_id = job["id"]
    final = ana.wait_job(job_id)
    check("P2", "El trabajador completa el trabajo", "completado", final["status"])
    status, bad, _ = ana.upload("05_metricas_corruptas.csv")
    bad_final = ana.wait_job(bad["id"])
    check("P3", "CSV con datos corruptos termina 'fallido' con error", "fallido", bad_final["status"])
    print(f"      error registrado: {bad_final.get('error')}")

    print("\n== Aislamiento entre usuarios ==")
    check("I1", "Beto consulta el trabajo de Ana por ID", 404, beto.request("GET", f"/api/jobs/{job_id}")[0])
    check("I2", "Beto intenta descargar el resultado de Ana", 404, beto.request("GET", f"/api/jobs/{job_id}/result")[0])
    check("I3", "Beto intenta eliminar el trabajo de Ana", 404, beto.request("DELETE", f"/api/jobs/{job_id}")[0])
    _, beto_jobs, _ = beto.request("GET", "/api/jobs")
    check("I4", "El listado de Beto no contiene trabajos de Ana", False, any(j["id"] == job_id for j in beto_jobs))

    print("\n== Autorizacion por rol (servidor) ==")
    check("R1", "Productor intenta listar usuarios (admin)", 403, ana.request("GET", "/api/admin/users")[0])
    check("R2", "Productor intenta ver todos los trabajos", 403, ana.request("GET", "/api/jobs?scope=all")[0])
    check("R3", "Productor intenta liberar un resultado", 403, ana.request("POST", f"/api/jobs/{job_id}/release")[0])
    check("R4", "Tecnico intenta crear usuarios", 403, carla.request(
        "POST", "/api/admin/users", {"username": "intruso", "password": "Intruso12345", "role": "admin"})[0])
    check("R5", "Tecnico ve todos los trabajos", 200, carla.request("GET", "/api/jobs?scope=all")[0])
    check("R6", "Admin NO puede leer el contenido del analisis (minimo privilegio)", 403,
          admin.request("GET", f"/api/jobs/{job_id}/result")[0])

    print("\n== Regla de negocio: liberacion tecnica ==")
    check("N1", "Ana descarga antes de la liberacion", 403, ana.request("GET", f"/api/jobs/{job_id}/result")[0])
    check("N2", "Carla (tecnico) revisa el resultado", 200, carla.request("GET", f"/api/jobs/{job_id}/result")[0])
    check("N3", "Carla libera el resultado de Ana", 200, carla.request("POST", f"/api/jobs/{job_id}/release")[0])
    status, data, _ = ana.request("GET", f"/api/jobs/{job_id}/result")
    check("N4", "Ana descarga despues de la liberacion", 200, status)
    expected_sha = hashlib.sha256((DATASET / "01_repo_tienda_web.csv").read_bytes()).hexdigest()
    check("N5", "El resultado referencia el SHA-256 del original", expected_sha,
          data.get("_metadatos", {}).get("sha256_original") if isinstance(data, dict) else None)
    _, own, _ = carla.upload("03_bitacora_revision.txt")
    carla.wait_job(own["id"])
    check("N6", "Segregacion: Carla no puede liberar su propio trabajo", 403,
          carla.request("POST", f"/api/jobs/{own['id']}/release")[0])

    print("\n== Auditoria ==")
    _, trail, _ = admin.request("GET", f"/api/admin/audit?resource=job:{job_id}")
    actions = {e["action"] + ":" + e["outcome"] for e in trail}
    for needed in ("CARGA:OK", "TRABAJO_COMPLETADO:OK", "LIBERACION:OK", "DESCARGA:OK", "DESCARGA:DENEGADO",
                   "ACCESO_AJENO:DENEGADO"):
        check("U" + str(len(results)), f"Trazabilidad del trabajo incluye {needed}", True, needed in actions)
    print("      cadena de custodia:")
    for e in sorted(trail, key=lambda x: x["ts"]):
        print(f"        {e['ts'][:19]}  {e['username']:<22} {e['action']:<20} {e['outcome']}")

    print("\n== Sesiones ==")
    ana.request("POST", "/api/auth/logout")
    stale = Client("ana-vieja")
    stale.cookie = ana.cookie
    check("S1", "Token anterior queda revocado tras cerrar sesion", 401, stale.request("GET", "/api/auth/me")[0])

    passed = sum(r["resultado"] == "PASA" for r in results)
    print(f"\nRESUMEN: {passed}/{len(results)} pruebas superadas")
    path = save_results("pruebas_funcionales", results)
    print(f"Evidencia guardada en {path}")
    raise SystemExit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
