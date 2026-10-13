-- Smart DEM — schéma SQLite v3 (dem_database.db)
-- Installation neuve : ce fichier crée tout. Base existante (v1/v2) : les tables manquantes sont créées ici, les colonnes
-- ajoutées plus tard sont ajoutées par database.MIGRATIONS (migrations idempotentes). Ne jamais indexer ici une colonne
-- ajoutée par migration : la base antérieure ne l'a pas encore à ce moment.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '3');

-- ===== Utilisateurs (connexion par PIN à 4 chiffres) =====
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    last_name     TEXT NOT NULL,
    first_name    TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('accueil','medecin','radio','pharmacie','labo')),
    specialty     TEXT,
    pin_salt      TEXT NOT NULL,
    pin_hash      TEXT NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1,
    signature_b64 TEXT,                       -- GRIFFE (cachet) du médecin, PNG transparent en base64
    sign_b64      TEXT,                       -- SIGNATURE manuscrite du médecin (v3)
    services      TEXT,                       -- v3 : services pris en charge (codes séparés par des virgules)
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
    full_name      TEXT    NOT NULL,              -- "NOM Prénom" (dérivé, conservé pour compatibilité)
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
    patient_ident  TEXT,                          -- v3 : N° d'identification (carte d'identité, dossier…) facultatif
    called_user_id INTEGER,                       -- v3 : médecin / agent qui a appelé (isolation multi-comptes)
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
    notes          TEXT,
    outcome        TEXT                           -- v3 : CLOSED | INTERRUPTED
);
CREATE INDEX IF NOT EXISTS idx_cons_adm ON consultations(admission_id, ended_at);

-- ===== Ordonnance numérique (QR + code-barres) =====
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
    ticket_label   TEXT NOT NULL,
    exam_type      TEXT,
    region         TEXT,
    side           TEXT,
    clinical_info  TEXT,
    urgent         INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'PENDING'
                   CHECK (status IN ('PENDING','CALLED','DONE','AWAITING_PRINT','CANCELLED')),
    created_at     TEXT NOT NULL,
    queue_ts       TEXT NOT NULL,
    called_at      TEXT,
    called_by      TEXT,
    skipped        INTEGER NOT NULL DEFAULT 0,
    done_at        TEXT,
    tech_user_id   INTEGER REFERENCES users(id),
    result_note    TEXT,
    instructions   TEXT                           -- v3 : consignes spécifiques du médecin
);
CREATE INDEX IF NOT EXISTS idx_rad_status ON radiology_requests(status, urgent, queue_ts);
CREATE INDEX IF NOT EXISTS idx_rad_doc    ON radiology_requests(doctor_user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_rad_cons   ON radiology_requests(consultation_id);

-- ===== Demandes d'analyses -> Laboratoire =====
CREATE TABLE IF NOT EXISTS lab_requests (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid           TEXT NOT NULL UNIQUE,
    consultation_id INTEGER NOT NULL REFERENCES consultations(id),
    admission_id   INTEGER NOT NULL REFERENCES admissions(id),
    doctor_user_id INTEGER REFERENCES users(id),
    items_json     TEXT NOT NULL,
    clinical_info  TEXT,
    created_at     TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'PENDING',   -- v3 : PENDING | IN_PROGRESS | DONE
    ticket_label   TEXT,                              -- v3 : BIO-001
    urgent         INTEGER NOT NULL DEFAULT 0,
    queue_ts       TEXT,
    done_at        TEXT,
    tech_user_id   INTEGER
);

-- ===== Résultats (clichés, comptes rendus, résultats de laboratoire) renvoyés au médecin =====
CREATE TABLE IF NOT EXISTS results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL CHECK (kind IN ('radio','lab')),
    request_id  INTEGER NOT NULL,
    filename    TEXT,
    mime        TEXT,
    data_b64    TEXT,                              -- image (JPEG/PNG) ou PDF, en base64
    report_text TEXT,
    created_at  TEXT NOT NULL,
    user_id     INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_results ON results(kind, request_id);

-- ===== Médicaments (nomenclature importable ; autocomplétion ; s'enrichit avec l'usage) =====
CREATE TABLE IF NOT EXISTS drugs (
    name TEXT PRIMARY KEY COLLATE NOCASE,
    uses INTEGER NOT NULL DEFAULT 0
);

-- ===== Rendez-vous du laboratoire =====
CREATE TABLE IF NOT EXISTS appointments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL DEFAULT 'lab',
    last_name   TEXT NOT NULL,
    first_name  TEXT NOT NULL,
    birth_year  INTEGER,
    phone       TEXT,
    ident       TEXT,
    date        TEXT NOT NULL,                     -- AAAA-MM-JJ
    time        TEXT NOT NULL,                     -- HH:MM
    exam        TEXT,
    notes       TEXT,
    status      TEXT NOT NULL DEFAULT 'PLANNED' CHECK (status IN ('PLANNED','ARRIVED','DONE','CANCELLED')),
    created_at  TEXT NOT NULL,
    created_by  INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_appt_date ON appointments(date, time);

-- ===== File de synchronisation (offline-first) vers un serveur distant (FHIR) =====
CREATE TABLE IF NOT EXISTS sync_outbox (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    entity     TEXT NOT NULL,
    ref        INTEGER,
    payload    TEXT NOT NULL,                      -- Bundle FHIR (chiffré)
    status     TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','SENT')),
    attempts   INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    next_try   TEXT,
    created_at TEXT NOT NULL,
    sent_at    TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    admission_id INTEGER,
    action       TEXT NOT NULL,
    details      TEXT,
    station      TEXT,
    at           TEXT NOT NULL
);
