-- =====================================================================
-- QualiCode - Esquema de base de datos
-- Se ejecuta UNA sola vez, cuando el volumen pgdata esta vacio.
-- =====================================================================

-- Usuarios y roles ----------------------------------------------------
CREATE TABLE users (
    id             SERIAL PRIMARY KEY,
    username       VARCHAR(30)  NOT NULL UNIQUE,
    password_hash  TEXT         NOT NULL,              -- Argon2id, nunca texto plano
    role           VARCHAR(20)  NOT NULL
                   CHECK (role IN ('admin', 'tecnico', 'productor')),
    active         BOOLEAN      NOT NULL DEFAULT TRUE,
    token_version  INTEGER      NOT NULL DEFAULT 0,    -- invalida sesiones al cambiar
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Trabajos de procesamiento (tambien es la COLA) ------------------------
CREATE TABLE jobs (
    id             UUID         PRIMARY KEY,           -- no secuencial: evita enumeracion
    owner_id       INTEGER      NOT NULL REFERENCES users(id),
    original_name  VARCHAR(255) NOT NULL,
    stored_path    TEXT         NOT NULL,
    file_type      VARCHAR(10)  NOT NULL CHECK (file_type IN ('csv', 'txt')),
    size_bytes     INTEGER      NOT NULL,
    sha256         CHAR(64)     NOT NULL,
    status         VARCHAR(20)  NOT NULL DEFAULT 'pendiente'
                   CHECK (status IN ('pendiente', 'en_ejecucion', 'completado', 'fallido')),
    result_path    TEXT,
    error          TEXT,
    attempts       INTEGER      NOT NULL DEFAULT 0,
    worker_id      VARCHAR(64),
    -- Regla de negocio QualiCode: liberacion tecnica del resultado
    released       BOOLEAN      NOT NULL DEFAULT FALSE,
    released_by    INTEGER      REFERENCES users(id),
    released_at    TIMESTAMPTZ,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    started_at     TIMESTAMPTZ,
    finished_at    TIMESTAMPTZ
);
CREATE INDEX idx_jobs_queue ON jobs (status, created_at);
CREATE INDEX idx_jobs_owner ON jobs (owner_id, created_at DESC);

-- Latido de los trabajadores (observabilidad) --------------------------
CREATE TABLE worker_heartbeat (
    worker_id   VARCHAR(64) PRIMARY KEY,
    pid         INTEGER,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen   TIMESTAMPTZ NOT NULL DEFAULT now(),
    jobs_done   INTEGER     NOT NULL DEFAULT 0,
    jobs_failed INTEGER     NOT NULL DEFAULT 0
);

-- Auditoria: quien hizo que, cuando, desde donde y con que resultado ---
CREATE TABLE audit_log (
    id        BIGSERIAL    PRIMARY KEY,
    ts        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    user_id   INTEGER,
    username  VARCHAR(64),
    role      VARCHAR(20),
    action    VARCHAR(40)  NOT NULL,
    resource  TEXT,
    outcome   VARCHAR(10)  NOT NULL CHECK (outcome IN ('OK', 'DENEGADO', 'ERROR')),
    ip        VARCHAR(45),
    detail    TEXT
);
CREATE INDEX idx_audit_ts       ON audit_log (ts DESC);
CREATE INDEX idx_audit_user     ON audit_log (username, action, ts);
CREATE INDEX idx_audit_resource ON audit_log (resource);

-- La auditoria es de solo-anexar: nadie puede modificar ni borrar eventos
CREATE FUNCTION audit_log_inmutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log es inmutable: no se permite % ', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_audit_inmutable
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_inmutable();
