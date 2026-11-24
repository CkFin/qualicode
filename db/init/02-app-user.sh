#!/bin/sh
# Crea el usuario de base de datos de la aplicacion con MINIMO PRIVILEGIO:
#  - Sin permisos de DDL (no puede crear/borrar tablas).
#  - Sobre audit_log solo SELECT e INSERT (no UPDATE/DELETE).
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
CREATE ROLE ${APP_DB_USER} LOGIN PASSWORD '${APP_DB_PASSWORD}';
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO ${APP_DB_USER};
GRANT USAGE ON SCHEMA public TO ${APP_DB_USER};
GRANT SELECT, INSERT, UPDATE, DELETE ON users, jobs, worker_heartbeat TO ${APP_DB_USER};
GRANT SELECT, INSERT ON audit_log TO ${APP_DB_USER};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ${APP_DB_USER};
EOSQL

echo "Usuario de aplicacion ${APP_DB_USER} creado con privilegios minimos."
