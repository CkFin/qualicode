"""PRUEBA DE RECUPERACION Y PERSISTENCIA - QualiCode.

  R1  Trabajador detenido: los trabajos esperan en la cola ('pendiente') y se
      procesan al volver a iniciarlo.
  R2  Caida abrupta (docker kill) del trabajador DURANTE un trabajo: al
      reiniciar, el trabajo huerfano se recupera y se completa.
  R3  Reinicio de base de datos y API: los datos permanecen.
  R4  docker compose down + up (contenedores nuevos): los datos permanecen
      gracias a los volumenes.

Uso (en el servidor, necesita docker):
    cd /opt/qualicode && sudo ADMIN_PASS=... python3 tests/prueba_recuperacion.py
"""
import subprocess
import time
from pathlib import Path

from cliente import Client, admin_client, ensure_user, save_results

ROOT = Path(__file__).resolve().parent.parent
log = []


def compose(*args):
    cmd = ["docker", "compose", *args]
    print("   $", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def wait_health(timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if Client().request("GET", "/api/health")[0] == 200:
                return True
        except OSError:
            pass
        time.sleep(2)
    return False


def check(code, text, ok, extra=""):
    log.append({"id": code, "prueba": text, "resultado": "PASA" if ok else "FALLA", "detalle": extra})
    print(f"[{'PASA' if ok else 'FALLA'}] {code} {text} {extra}")


def status_of(client, jid):
    return client.request("GET", f"/api/jobs/{jid}")[1]["status"]


def main():
    admin = admin_client()
    pwd = ensure_user(admin, "tec_recuperacion", "tecnico")
    tec = Client("tec")
    tec.login("tec_recuperacion", pwd)

    print("\n== R1 Trabajador detenido ==")
    compose("stop", "worker")
    ids = [tec.upload("01_repo_tienda_web.csv")[1]["id"] for _ in range(3)]
    time.sleep(5)
    states = [status_of(tec, j) for j in ids]
    check("R1a", "Con el trabajador detenido los trabajos quedan en cola", all(s == "pendiente" for s in states), str(states))
    compose("start", "worker")
    states = [tec.wait_job(j)["status"] for j in ids]
    check("R1b", "Al reiniciar el trabajador procesa la cola pendiente", all(s == "completado" for s in states), str(states))

    print("\n== R2 Caida abrupta durante un trabajo ==")
    jid = tec.upload("04_metricas_ci_grande.csv")[1]["id"]
    for _ in range(30):
        if status_of(tec, jid) == "en_ejecucion":
            break
        time.sleep(0.5)
    compose("kill", "worker")  # SIGKILL: sin apagado limpio
    check("R2a", "El trabajo quedo 'en_ejecucion' al morir el trabajador", status_of(tec, jid) == "en_ejecucion")
    compose("start", "worker")
    job = tec.wait_job(jid)
    check("R2b", "El trabajo huerfano se recupera y completa", job["status"] == "completado",
          f"intentos={job['attempts']}")

    print("\n== R3 Reinicio de BD y API ==")
    compose("restart", "db", "api")
    check("R3a", "La API vuelve a estar disponible", wait_health())
    tec.login("tec_recuperacion", pwd)
    job = tec.request("GET", f"/api/jobs/{jid}")[1]
    check("R3b", "El trabajo sigue registrado tras el reinicio", job.get("status") == "completado")
    check("R3c", "El resultado sigue descargable", tec.request("GET", f"/api/jobs/{jid}/result")[0] == 200)

    print("\n== R4 Recrear todos los contenedores (down/up, sin -v) ==")
    compose("down")
    compose("up", "-d")
    check("R4a", "La plataforma vuelve a responder", wait_health())
    tec.login("tec_recuperacion", pwd)
    check("R4b", "Datos y resultados persisten en los volumenes",
          tec.request("GET", f"/api/jobs/{jid}/result")[0] == 200)

    passed = sum(r["resultado"] == "PASA" for r in log)
    print(f"\nRESUMEN: {passed}/{len(log)} pruebas superadas")
    print("Revise los logs del reinicio:  sudo docker compose logs --tail 30 worker")
    print(f"Evidencia guardada en {save_results('prueba_recuperacion', log)}")


if __name__ == "__main__":
    main()
