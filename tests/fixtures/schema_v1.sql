-- Smart DEM — schéma SQLite (dem_database.db)
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '1');

-- Une "garde" = une période de comptage. Réinitialiser les compteurs = fermer la garde et en ouvrir une nouvelle.
CREATE TABLE IF NOT EXISTS shifts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    started_by TEXT
);

-- Compteur de tickets par service et par garde (LAB-001, RAD-001...)
CREATE TABLE IF NOT EXISTS counters (
    shift_id     INTEGER NOT NULL REFERENCES shifts(id),
    service_code TEXT    NOT NULL,
    last_number  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (shift_id, service_code)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS admissions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    shift_id       INTEGER NOT NULL REFERENCES shifts(id),
    service_code   TEXT    NOT NULL,
    ticket_number  INTEGER NOT NULL,
    ticket_label   TEXT    NOT NULL,              -- ex: LAB-001 (jamais modifié par une correction)
    full_name      TEXT    NOT NULL,
    name_norm      TEXT    NOT NULL,              -- nom normalisé (sans accents, tokens triés) pour la détection
    birth_date     TEXT,                          -- AAAA-MM-JJ si saisie exacte, sinon NULL
    birth_year     INTEGER NOT NULL,              -- année de naissance (déduite de l'âge si besoin)
    gender         TEXT    NOT NULL CHECK (gender IN ('H','F')),
    triage_level   TEXT    CHECK (triage_level IN ('VERT','ORANGE','ROUGE')),  -- NULL hors Urgences / Méd. générale
    status         TEXT    NOT NULL DEFAULT 'WAITING'
                   CHECK (status IN ('WAITING','CALLED','DONE','CANCELLED')),
    created_at     TEXT    NOT NULL,
    called_at      TEXT,
    finished_at    TEXT,
    called_by      TEXT,
    modified_at    TEXT,
    modified_count INTEGER NOT NULL DEFAULT 0,
    station_name   TEXT,
    UNIQUE (shift_id, ticket_label)
);

CREATE INDEX IF NOT EXISTS idx_adm_shift   ON admissions(shift_id, created_at);
CREATE INDEX IF NOT EXISTS idx_adm_queue   ON admissions(status, service_code, triage_level, created_at);
CREATE INDEX IF NOT EXISTS idx_adm_revisit ON admissions(name_norm, gender, birth_year, created_at);

-- Historique des appels (alimentera l'écran TV via le réseau local)
CREATE TABLE IF NOT EXISTS calls (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    admission_id INTEGER NOT NULL REFERENCES admissions(id),
    called_at    TEXT    NOT NULL,
    station      TEXT,
    is_recall    INTEGER NOT NULL DEFAULT 0
);

-- Traçabilité des créations / corrections
CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    admission_id INTEGER,
    action       TEXT NOT NULL,
    details      TEXT,
    station      TEXT,
    at           TEXT NOT NULL
);
