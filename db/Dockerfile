# Imagen de PostgreSQL con el esquema incluido (no se monta codigo desde el host).
FROM postgres:16-alpine
COPY db/init/ /docker-entrypoint-initdb.d/
RUN chmod 0644 /docker-entrypoint-initdb.d/*
