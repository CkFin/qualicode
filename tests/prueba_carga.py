"""PRUEBA DE RENDIMIENTO - QualiCode.

Carga definida: N trabajos (por defecto 40) enviados con C clientes
concurrentes (por defecto 8), alternando los archivos validos del dataset
(01 ~2 KiB, 02 ~12 KiB, 03 ~6 KiB, 04 ~1.1 MiB). Mide:
  - latencia de la carga (la API responde sin esperar el procesamiento)
  - tiempo total hasta vaciar la cola y rendimiento (trabajos/minuto)
  - tiempo medio de espera en cola y de procesamiento

Mientras corre, observar recursos en otra terminal:
    sudo docker stats            (CPU/memoria por contenedor vs limites)
    bash tests/monitor_recursos.sh

Uso:  ADMIN_PASS=... python3 tests/prueba_carga.py [--jobs 40] [--concurrency 8]
Sugerencia: PROCESSING_DELAY_SECONDS=0 en .env mide el procesamiento real.
"""
import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from cliente import Client, admin_client, ensure_user, save_results

FILES = ["01_repo_tienda_web.csv", "02_repo_app_pagos.csv", "03_bitacora_revision.txt", "04_metricas_ci_grande.csv"]


def pct(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=40)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()

    admin = admin_client()
    password = ensure_user(admin, "tec_carga", "tecnico")  # tecnico: sin cuota de cola
    client = Client("carga")
    assert client.login("tec_carga", password) == 200

    print(f"Enviando {args.jobs} trabajos con {args.concurrency} clientes concurrentes...")

    def send(i):
        t0 = time.perf_counter()
        status, job, _ = client.upload(FILES[i % len(FILES)])
        return status, job.get("id") if isinstance(job, dict) else None, (time.perf_counter() - t0) * 1000

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        sent = list(pool.map(send, range(args.jobs)))
    upload_s = time.perf_counter() - start
    ids = [jid for status, jid, _ in sent if status == 201]
    latencies = [ms for _, _, ms in sent]
    print(f"Cargas aceptadas: {len(ids)}/{args.jobs} en {upload_s:.1f}s "
          f"(latencia p50 {pct(latencies, 50):.0f} ms, p95 {pct(latencies, 95):.0f} ms)")

    print("Esperando a que el trabajador vacie la cola...")
    pending = set(ids)
    final = {}
    while pending:
        for jid in list(pending):
            status, job, _ = client.request("GET", f"/api/jobs/{jid}")
            if status == 200 and job["status"] in ("completado", "fallido"):
                final[jid] = job
                pending.discard(jid)
        if pending:
            print(f"  quedan {len(pending)} trabajos...", end="\r")
            time.sleep(2)
    total_s = time.perf_counter() - start

    def secs(a, b):
        return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds()

    waits = [secs(j["created_at"], j["started_at"]) for j in final.values()]
    procs = [secs(j["started_at"], j["finished_at"]) for j in final.values()]
    summary = {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "trabajos_enviados": args.jobs,
        "concurrencia": args.concurrency,
        "aceptados": len(ids),
        "completados": sum(j["status"] == "completado" for j in final.values()),
        "fallidos": sum(j["status"] == "fallido" for j in final.values()),
        "bytes_totales": sum(j["size_bytes"] for j in final.values()),
        "latencia_carga_ms": {"p50": round(pct(latencies, 50)), "p95": round(pct(latencies, 95)),
                              "max": round(max(latencies))},
        "tiempo_total_s": round(total_s, 1),
        "rendimiento_trabajos_min": round(len(final) / total_s * 60, 1),
        "espera_en_cola_s": {"promedio": round(statistics.fmean(waits), 2), "max": round(max(waits), 2)},
        "procesamiento_s": {"promedio": round(statistics.fmean(procs), 2), "max": round(max(procs), 2)},
        "workers": sorted({j["worker_id"] for j in final.values() if j.get("worker_id")}),
    }
    print("\n=== RESULTADO DE LA PRUEBA DE CARGA ===")
    for k, v in summary.items():
        print(f"  {k:<26} {v}")
    print(f"Evidencia guardada en {save_results('prueba_carga', summary)}")


if __name__ == "__main__":
    main()
