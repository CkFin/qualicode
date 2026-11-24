"""Consola de administracion (dentro del contenedor api).

Ejemplos:
  docker compose exec api python -m api.manage list-users
  docker compose exec -it api python -m api.manage create-user prueba1 productor
  docker compose exec api python -m api.manage set-role prueba1 tecnico
  docker compose exec api python -m api.manage set-active prueba1 --off
"""
import argparse
import getpass
import sys

from api import database as db
from api.security.passwords import check_policy, hash_password
from api.security.permissions import ROLES


def _audit(action: str, username: str, detail: str) -> None:
    db.audit_event(username="consola", role="admin-cli", action=action,
                   resource=f"user:{username}", outcome="OK", ip="localhost", detail=detail)


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m api.manage")
    sub = parser.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create-user", help="Crear usuario")
    c.add_argument("username")
    c.add_argument("role", choices=list(ROLES))
    c.add_argument("--password", help="Si se omite se pide de forma oculta")

    r = sub.add_parser("set-role", help="Cambiar rol")
    r.add_argument("username")
    r.add_argument("role", choices=list(ROLES))

    a = sub.add_parser("set-active", help="Activar/desactivar")
    a.add_argument("username")
    a.add_argument("--off", action="store_true")

    sub.add_parser("list-users", help="Listar usuarios")
    args = parser.parse_args()
    db.open_pool()

    if args.cmd == "list-users":
        print(f"{'ID':>3}  {'USUARIO':<20} {'ROL':<10} ACTIVO")
        for u in db.query("SELECT id, username, role, active FROM users ORDER BY id"):
            print(f"{u['id']:>3}  {u['username']:<20} {u['role']:<10} {'si' if u['active'] else 'no'}")
        return 0

    if args.cmd == "create-user":
        password = args.password or getpass.getpass("Contrasena: ")
        problem = check_policy(password, args.username)
        if problem:
            print(f"ERROR: {problem}", file=sys.stderr)
            return 1
        row = db.query_one(
            """INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)
               ON CONFLICT (username) DO NOTHING RETURNING id""",
            (args.username.lower(), hash_password(password), args.role))
        if not row:
            print("ERROR: el usuario ya existe", file=sys.stderr)
            return 1
        _audit("USUARIO_CREADO", args.username, f"rol {args.role}")
        print(f"Usuario '{args.username}' creado con rol '{args.role}' (id {row['id']})")
        return 0

    if args.cmd == "set-role":
        n = db.execute("UPDATE users SET role = %s, token_version = token_version + 1 WHERE username = %s",
                       (args.role, args.username))
        if n:
            _audit("USUARIO_MODIFICADO", args.username, f"rol -> {args.role}")
        print("Rol actualizado" if n else "Usuario no encontrado")
        return 0 if n else 1

    if args.cmd == "set-active":
        n = db.execute("UPDATE users SET active = %s, token_version = token_version + 1 WHERE username = %s",
                       (not args.off, args.username))
        if n:
            _audit("USUARIO_MODIFICADO", args.username, "desactivado" if args.off else "activado")
        print("Estado actualizado" if n else "Usuario no encontrado")
        return 0 if n else 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
