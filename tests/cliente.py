"""Cliente HTTP minimo para las pruebas (solo biblioteca estandar de Python 3).

Las pruebas se ejecutan en el servidor sin instalar nada:  python3 tests/<prueba>.py
"""
import json
import os
import secrets
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE_URL = os.getenv("QUALICODE_URL", "http://localhost").rstrip("/")
DATASET = Path(__file__).resolve().parent.parent / "dataset"
RESULTS = Path(__file__).resolve().parent / "resultados"


class Client:
    def __init__(self, name: str = "", base: str = BASE_URL):
        self.name, self.base, self.cookie = name, base, None

    def request(self, method: str, path: str, json_body=None, body: bytes | None = None,
                headers: dict | None = None):
        headers = dict(headers or {})
        if json_body is not None:
            body = json.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"
        if self.cookie:
            headers["Cookie"] = self.cookie
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, self._parse(resp), resp.headers
        except urllib.error.HTTPError as err:
            return err.code, self._parse(err), err.headers

    def _parse(self, resp):
        cookie = resp.headers.get("Set-Cookie")
        if cookie and cookie.startswith("qualicode_session="):
            self.cookie = cookie.split(";", 1)[0]
        raw = resp.read()
        try:
            return json.loads(raw)
        except ValueError:
            return raw.decode(errors="replace")

    # ----------------------------------------------------------- atajos
    def login(self, username: str, password: str) -> int:
        status, _, _ = self.request("POST", "/api/auth/login", {"username": username, "password": password})
        return status

    def upload_bytes(self, filename: str, content: bytes):
        boundary = uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
        return self.request("POST", "/api/jobs", body=body,
                            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})

    def upload(self, dataset_file: str):
        return self.upload_bytes(dataset_file, (DATASET / dataset_file).read_bytes())

    def wait_job(self, job_id: str, timeout: float = 120) -> dict:
        end = time.time() + timeout
        while time.time() < end:
            status, job, _ = self.request("GET", f"/api/jobs/{job_id}")
            if status == 200 and job["status"] in ("completado", "fallido"):
                return job
            time.sleep(1)
        raise TimeoutError(f"El trabajo {job_id} no termino en {timeout}s")


def ensure_user(admin: Client, username: str, role: str) -> str:
    """Crea el usuario (o restablece su clave) y devuelve una contrasena aleatoria nueva."""
    password = "Prueba" + secrets.token_hex(6) + "7"
    status, _, _ = admin.request("POST", "/api/admin/users",
                                 {"username": username, "password": password, "role": role})
    if status == 409:
        _, users, _ = admin.request("GET", "/api/admin/users")
        uid = next(u["id"] for u in users if u["username"] == username)
        admin.request("PATCH", f"/api/admin/users/{uid}", {"password": password, "role": role, "active": True})
    return password


def admin_client() -> Client:
    import getpass
    user = os.getenv("ADMIN_USER", "admin")
    password = os.getenv("ADMIN_PASS") or getpass.getpass(f"Contrasena de '{user}': ")
    client = Client("admin")
    if client.login(user, password) != 200:
        raise SystemExit("No se pudo iniciar sesion como administrador")
    return client


def save_results(name: str, data) -> Path:
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{name}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path
