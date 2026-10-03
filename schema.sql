-- Smart DEM — schéma SQLite v2 (dem_database.db)
-- Installation neuve : ce fichier crée tout. Base v1.0.0 existante : les tables manquantes sont créées ici,
-- et les colonnes ajoutées à `admissions` le sont par MIGRATIONS[2] (database.py). Ne jamais indexer ici une colonne
-- ajoutée par migration (la base v1 ne l'a pas encore à ce moment).
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '2');

-- ===== Utilisateurs (connexion par PIN à 4 chiffres) =====
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    last_name     TEXT NOT NULL,
    first_name    TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('accueil','medecin','radio','pharmacie')),
    specialty     TEXT,
    pin_salt      TEXT NOT NULL,
    pin_hash      TEXT NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1,
    signature_b64 TEXT,                       -- griffe / tampon du médecin (PNG transparent, base64)
    failed_count  INTEGER NOT NULL DEFAULT 0, -- verrouillage temporaire après 5 échecs
    locked_until  TEXT,
    created_at    TEXT NOT NULL
);

-- ===== Gardes / compteurs / admissions =====
CREATE TABLE IF NOT EXISTS shifts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    started_by TEXT
);

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
    full_name      TEXT    NOT NULL,              -- "NOM Prénom" (dérivé, conservé pour compatibilité v1)
    name_norm      TEXT    NOT NULL,              -- nom+prénom normalisés (sans accents, tokens triés)
    birth_date     TEXT,
    birth_year     INTEGER NOT NULL,
    gender         TEXT    NOT NULL CHECK (gender IN ('H','F')),
    triage_level   TEXT    CHECK (triage_level IN ('VERT','ORANGE','ROUGE')),
    status         TEXT    NOT NULL DEFAULT 'WAITING'
                   CHECK (status IN ('WAITING','CALLED','DONE','CANCELLED')),
    created_at     TEXT    NOT NULL,
    called_at      TEXT,
    finished_at    TEXT,
    called_by      TEXT,
    modified_at    TEXT,
    modified_count INTEGER NOT NULL DEFAULT 0,
    station_name   TEXT,
    last_name      TEXT,                          -- v2 : Nom de famille
    first_name     TEXT,                          -- v2 : Prénom
    created_by     INTEGER,                       -- v2 : utilisateur ayant enregistré
    UNIQUE (shift_id, ticket_label)
);
CREATE INDEX IF NOT EXISTS idx_adm_shift   ON admissions(shift_id, created_at);
CREATE INDEX IF NOT EXISTS idx_adm_queue   ON admissions(status, service_code, triage_level, created_at);
CREATE INDEX IF NOT EXISTS idx_adm_revisit ON admissions(name_norm, gender, birth_year, created_at);

CREATE TABLE IF NOT EXISTS calls (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    admission_id INTEGER NOT NULL REFERENCES admissions(id),
    called_at    TEXT    NOT NULL,
    station      TEXT,
    is_recall    INTEGER NOT NULL DEFAULT 0
);

-- ===== Consultation (poste médecin) =====
CREATE TABLE IF NOT EXISTS consultations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    admission_id   INTEGER NOT NULL REFERENCES admissions(id),
    doctor_user_id INTEGER REFERENCES users(id),
    station        TEXT,
    started_at     TEXT NOT NULL,
    ended_at       TEXT,
    diagnosis      TEXT,
    notes          TEXT
);
CREATE INDEX IF NOT EXISTS idx_cons_adm ON consultations(admission_id, ended_at);

-- ===== Ordonnance numérique (QR sécurisé) =====
CREATE TABLE IF NOT EXISTS prescriptions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid           TEXT NOT NULL UNIQUE,          -- 32 hex, encodé dans le QR
    consultation_id INTEGER NOT NULL REFERENCES consultations(id),
    admission_id   INTEGER NOT NULL REFERENCES admissions(id),
    doctor_user_id INTEGER REFERENCES users(id),
    items_json     TEXT NOT NULL,                 -- [{drug, dosage, duration}]
    notes          TEXT,
    canonical      TEXT NOT NULL,                 -- contenu figé signé
    content_hash   TEXT NOT NULL,                 -- SHA-256 du contenu figé
    sig            TEXT NOT NULL,                 -- HMAC (16 hex) imprimé dans le QR
    status         TEXT NOT NULL DEFAULT 'CREATED' CHECK (status IN ('CREATED','SENT','DISPENSED')),
    created_at     TEXT NOT NULL,
    sent_at        TEXT,
    dispensed_at   TEXT,
    dispensed_by   INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_rx_cons ON prescriptions(consultation_id);

-- File de transit médecin -> pharmacie (JSON léger)
CREATE TABLE IF NOT EXISTS transit_queue (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    channel    TEXT NOT NULL,                     -- 'pharmacie'
    ref_uuid   TEXT NOT NULL,
    payload    TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','DONE')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_transit ON transit_queue(channel, status);

-- ===== Radiologie =====
CREATE TABLE IF NOT EXISTS radiology_requests (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid           TEXT NOT NULL UNIQUE,
    source         TEXT NOT NULL CHECK (source IN ('MEDECIN','RECEPTION')),
    consultation_id INTEGER REFERENCES consultations(id),
    admission_id   INTEGER REFERENCES admissions(id),
    doctor_user_id INTEGER REFERENCES users(id),
    ticket_label   TEXT NOT NULL,                 -- numéro de passage RAD-001
    exam_type      TEXT,                          -- Radio X / Échographie / Scanner
    region         TEXT,
    side           TEXT,                          -- Droit / Gauche / Bilatéral / N/A
    clinical_info  TEXT,
    urgent         INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'PENDING'
                   CHECK (status IN ('PENDING','CALLED','DONE','AWAITING_PRINT','CANCELLED')),
    created_at     TEXT NOT NULL,
    queue_ts       TEXT NOT NULL,                 -- ordre de passage (remis à jour si le patient est reporté)
    called_at      TEXT,
    called_by      TEXT,
    skipped        INTEGER NOT NULL DEFAULT 0,
    done_at        TEXT,
    tech_user_id   INTEGER REFERENCES users(id),
    result_note    TEXT
);
CREATE INDEX IF NOT EXISTS idx_rad_status ON radiology_requests(status, urgent, queue_ts);
CREATE INDEX IF NOT EXISTS idx_rad_doc    ON radiology_requests(doctor_user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_rad_cons   ON radiology_requests(consultation_id);

-- ===== Demandes d'analyses (imprimé laboratoire) =====
CREATE TABLE IF NOT EXISTS lab_requests (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid           TEXT NOT NULL UNIQUE,
    consultation_id INTEGER NOT NULL REFERENCES consultations(id),
    admission_id   INTEGER NOT NULL REFERENCES admissions(id),
    doctor_user_id INTEGER REFERENCES users(id),
    items_json     TEXT NOT NULL,
    clinical_info  TEXT,
    created_at     TEXT NOT NULL
);

-- ===== Médicaments (saisie semi-automatique ; s'enrichit avec l'usage) =====
CREATE TABLE IF NOT EXISTS drugs (
    name TEXT PRIMARY KEY COLLATE NOCASE,
    uses INTEGER NOT NULL DEFAULT 0
);

-- ===== Traçabilité =====
CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    admission_id INTEGER,
    action       TEXT NOT NULL,
    details      TEXT,
    station      TEXT,
    at           TEXT NOT NULL
);
