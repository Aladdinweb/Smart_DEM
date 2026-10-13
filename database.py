"""Couche SQLite : utilisateurs (PIN), gardes, admissions, consultations, ordonnances sécurisées, radiologie,
analyses, pharmacie. Toutes les méthodes publiques de RPC_METHODS sont aussi appelables à distance via le Hub."""
import hashlib, hmac, json, os, re, secrets, sqlite3, threading, unicodedata, uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from config_manager import resource_path
from crypto import Crypto
from data_structures import CONSULT_SERVICES, SERVICE_BY_CODE
from medical_data import DRUGS_SEED

FMT = "%Y-%m-%d %H:%M:%S"
SCHEMA_VERSION = 4
from functions import ALERT_FUNCTIONS, DEFAULT_SERVICES, ROLE_OF, ROLES, default_function, match_function   # noqa: E402
def _cols(c, table):
    return {r[1] for r in c.execute(f"PRAGMA table_info({table})")}


def _add_col(c, table, ddl):
    if ddl.split()[0] not in _cols(c, table):
        c.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


USERS_DDL = """CREATE TABLE users_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT, last_name TEXT NOT NULL, first_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('accueil','medecin','radio','pharmacie','labo','soins','coord_med','coord_para')),
    specialty TEXT, pin_salt TEXT NOT NULL, pin_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
    signature_b64 TEXT, sign_b64 TEXT, services TEXT, function TEXT, failed_count INTEGER NOT NULL DEFAULT 0, locked_until TEXT, created_at TEXT NOT NULL)"""


def _m2(c):      # v1 -> v2 : Nom / Prénom séparés
    for col in ("last_name TEXT", "first_name TEXT", "created_by INTEGER"):
        _add_col(c, "admissions", col)
    c.execute("UPDATE admissions SET last_name = full_name, first_name = '' WHERE last_name IS NULL")


def _m3(c):      # v2 -> v3 : identifiant patient, isolation multi-comptes, laboratoire, résultats, rôle « labo », signature
    for col in ("patient_ident TEXT", "called_user_id INTEGER"):
        _add_col(c, "admissions", col)
    _add_col(c, "consultations", "outcome TEXT")
    _add_col(c, "radiology_requests", "instructions TEXT")
    for col in ("status TEXT NOT NULL DEFAULT 'PENDING'", "ticket_label TEXT", "urgent INTEGER NOT NULL DEFAULT 0",
                "queue_ts TEXT", "done_at TEXT", "tech_user_id INTEGER"):
        _add_col(c, "lab_requests", col)
    c.execute("UPDATE lab_requests SET status='DONE' WHERE ticket_label IS NULL")   # imprimés déjà remis en v2
    row = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
    if row and ("'labo'" not in row[0] or "sign_b64" not in row[0] or "services" not in row[0]):                  # reconstruction de `users` (CHECK du rôle)
        keep = [x for x in ("id", "last_name", "first_name", "role", "specialty", "pin_salt", "pin_hash", "active",
                            "signature_b64", "sign_b64", "services", "failed_count", "locked_until", "created_at") if x in _cols(c, "users")]
        c.execute("DROP TABLE IF EXISTS users_new")
        c.execute(USERS_DDL)
        c.execute(f"INSERT INTO users_new({','.join(keep)}) SELECT {','.join(keep)} FROM users")
        c.execute("DROP TABLE users")
        c.execute("ALTER TABLE users_new RENAME TO users")


ENC_FIELDS = {"vitals_json", "data_json", "diagnosis", "notes", "items_json", "canonical", "clinical_info", "instructions", "result_note", "report_text", "data_b64", "payload"}
def _m4(c):      # v3 -> v4 : fonctions officielles, rôles soins / coordinateurs, relève de garde (vitals et drafts créées par schema.sql)
    for col in ("handover_note TEXT", "handover_from INTEGER", "handover_at TEXT"):
        _add_col(c, "admissions", col)
    row = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
    if row and ("'coord_med'" not in row[0] or "function" not in row[0]):
        keep = [x for x in ("id", "last_name", "first_name", "role", "specialty", "pin_salt", "pin_hash", "active", "signature_b64", "sign_b64",
                            "services", "failed_count", "locked_until", "created_at") if x in _cols(c, "users")]
        c.execute("DROP TABLE IF EXISTS users_new")
        c.execute(USERS_DDL)
        c.execute(f"INSERT INTO users_new({','.join(keep)}) SELECT {','.join(keep)} FROM users")
        c.execute("DROP TABLE users")
        c.execute("ALTER TABLE users_new RENAME TO users")
    for u in c.execute("SELECT id, role, specialty, services FROM users WHERE function IS NULL OR function=''").fetchall():
        services = [s for s in (u["services"] or "").split(",") if s]
        fn = match_function(u["specialty"])
        if fn and u["role"] in ("accueil", "medecin"):        # ex. compte « Accueil / ATS » -> fonction ATS -> espace Soins & Triage
            c.execute("UPDATE users SET function=?, role=? WHERE id=?", (fn, ROLE_OF[fn], u["id"]))
        else:
            c.execute("UPDATE users SET function=? WHERE id=?", (default_function(u["role"], services), u["id"]))


MIGRATIONS = {2: _m2, 3: _m3, 4: _m4}


def now():
    return datetime.now().strftime(FMT)


def now_us():
    """Horodatage à la microseconde : ordre de passage stable même si deux événements ont lieu dans la même seconde."""
    return datetime.now().strftime(FMT + ".%f")


def norm_name(last, first=""):
    """Sans accents, minuscules, tokens triés : 'BENALI Ahmed' == 'ahmed benali'."""
    s = unicodedata.normalize("NFKD", f"{last or ''} {first or ''}")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return " ".join(sorted(re.sub(r"[^a-z0-9 ]", " ", s).split()))


def display_name(r):
    n = f"{(r.get('last_name') or '').upper()} {r.get('first_name') or ''}".strip()
    return n or r.get("full_name", "")


def parse_age_or_birth(text):
    """'35' | '1989' | '12/05/1989' -> {'birth_date','birth_year'} ou None si invalide."""
    t = (text or "").strip()
    today = date.today()
    if re.fullmatch(r"\d{1,3}", t):
        age = int(t)
        return {"birth_date": None, "birth_year": today.year - age} if age <= 120 else None
    if re.fullmatch(r"(19|20)\d{2}", t):
        y = int(t)
        return {"birth_date": None, "birth_year": y} if y <= today.year else None
    m = re.fullmatch(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", t)
    if m:
        d, mo, y = map(int, m.groups())
        try:
            dt = date(y, mo, d)
        except ValueError:
            return None
        return {"birth_date": dt.isoformat(), "birth_year": y} if (dt <= today and y >= 1900) else None
    return None


def age_from_row(r):
    today = date.today()
    if r.get("birth_date"):
        b = date.fromisoformat(r["birth_date"])
        return today.year - b.year - ((today.month, today.day) < (b.month, b.day))
    return today.year - r["birth_year"]


def birth_text(r):
    return date.fromisoformat(r["birth_date"]).strftime("%d/%m/%Y") if r.get("birth_date") else str(age_from_row(r))


def _hash_pin(pin, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt_hex), 100_000).hex()


_RADIO_SELECT = """SELECT r.*, a.last_name, a.first_name, a.full_name, a.birth_year, a.birth_date, a.gender,
    u.last_name AS doc_last, u.first_name AS doc_first,
    (SELECT COUNT(*) FROM results rs WHERE rs.kind='radio' AND rs.request_id=r.id) AS n_results
    FROM radiology_requests r LEFT JOIN admissions a ON a.id=r.admission_id
    LEFT JOIN users u ON u.id=r.doctor_user_id"""

RPC_METHODS = (
    "current_shift", "shift_info", "reset_shift", "get", "add_admission", "update_admission", "history", "stats",
    "find_revisit", "queue", "current_called", "call_next", "recall", "finish", "release_patient",
    "count_users", "list_users", "create_user", "update_user", "delete_user", "reset_user_pin", "change_own_pin",
    "verify_pin", "get_user", "set_user_image", "set_signature", "list_drug_names", "add_drug", "import_drugs",
    "start_consultation", "close_consultation",
    "create_prescription", "get_prescription", "send_to_pharmacy", "pharmacy_queue", "pharmacy_lookup", "pharmacy_dispense",
    "create_radio_request", "radio_queue", "radio_awaiting", "radio_call_next", "radio_recall", "radio_validate",
    "radio_requests_for_doctor", "radio_for_consultation",
    "create_lab_request", "lab_queue", "lab_start", "lab_validate", "lab_requests_for_doctor", "lab_for_consultation",
    "add_result", "list_results", "get_result", "search_patients", "patient_record", "tv_state", "tv_set", "tv_clear",
    "record_vitals", "vitals_for_admission", "orient_patient", "coord_overview", "reassign_admission", "save_draft", "get_draft", "delete_draft",
    "handover_start", "handover_list", "take_over", "tv_voice", "tv_announce", "tv_announce_clear", "tv_pairs", "tv_pair", "tv_unpair",
    "tv_screens", "tv_set_screens", "create_appointment", "update_appointment", "delete_appointment", "list_appointments",
    "appointment_days", "stats_report",
)


class Database:
    def __init__(self, path, crypto=None):
        self.path = path
        self.crypto = crypto or Crypto.for_dir(os.path.dirname(os.path.abspath(path)))
        self._ctx = threading.local()      # identité de session imposée par le Hub (JWT)
        self.sync_enabled, self.backup_dir = False, None
        self.call_listeners = []
        self.tv_listeners = []
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")      # durabilité maximale : coupure de courant sans perte ni corruption
        self.conn.execute("PRAGMA foreign_keys=ON")
        with open(resource_path("schema.sql"), encoding="utf-8") as f:
            self.conn.executescript(f.read())
        self.conn.commit()
        self._migrate()
        self._ensure_key()
        self._seed_drugs()
        self._encrypt_legacy()

    # ---------- infrastructure ----------
    @contextmanager
    def _tx(self):
        with self.lock:
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def _dec(self, d):
        for k in ENC_FIELDS.intersection(d):
            d[k] = self.crypto.dec(d[k])
        return d

    def _enc(self, text):
        return self.crypto.enc(text)

    def _one(self, sql, args=()):
        with self.lock:
            r = self.conn.execute(sql, args).fetchone()
        return self._dec(dict(r)) if r else None

    def _all(self, sql, args=()):
        with self.lock:
            return [self._dec(dict(r)) for r in self.conn.execute(sql, args)]

    def _encrypt_legacy(self):
        """Chiffre une fois les anciennes données cliniques (créées avant l'activation du chiffrement)."""
        if not self.crypto.available or self._meta("enc_legacy") == "1":
            return
        spec = {"consultations": ("diagnosis", "notes"), "prescriptions": ("items_json", "notes", "canonical"),
                "lab_requests": ("items_json", "clinical_info"), "radiology_requests": ("clinical_info", "instructions", "result_note"),
                "results": ("report_text", "data_b64"), "transit_queue": ("payload",)}
        with self._tx() as c:
            for table, cols in spec.items():
                for r in c.execute(f"SELECT id, {','.join(cols)} FROM {table}").fetchall():
                    for col in cols:
                        v = r[col]
                        if v and not v.startswith("enc1:"):
                            c.execute(f"UPDATE {table} SET {col}=? WHERE id=?", (self.crypto.enc(v), r["id"]))
            self._set_meta(c, "enc_legacy", "1")

    def _migrate(self):
        cur = int(self._one("SELECT value FROM meta WHERE key='schema_version'")["value"])
        if cur > SCHEMA_VERSION:
            raise RuntimeError("Base de données plus récente que le programme : mettez à jour Smart DEM.")
        if cur == SCHEMA_VERSION:
            return
        import os
        self.backup(os.path.join(os.path.dirname(self.path), "backups"))   # sécurité avant migration
        self.conn.execute("PRAGMA foreign_keys=OFF")
        try:
            for v in range(cur + 1, SCHEMA_VERSION + 1):
                MIGRATIONS[v](self.conn)
                self.conn.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(v),))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            self.conn.execute("PRAGMA foreign_keys=ON")

    def _ensure_key(self):
        with self._tx() as c:
            if not c.execute("SELECT 1 FROM meta WHERE key='signing_key'").fetchone():
                c.execute("INSERT INTO meta(key,value) VALUES ('signing_key',?)", (secrets.token_hex(32),))
            if not c.execute("SELECT 1 FROM meta WHERE key='jwt_key'").fetchone():
                c.execute("INSERT INTO meta(key,value) VALUES ('jwt_key',?)", (secrets.token_hex(32),))

    def jwt_secret(self):
        return self._meta("jwt_key")

    def _sign(self, text):
        key = self._one("SELECT value FROM meta WHERE key='signing_key'")["value"]
        return hmac.new(key.encode(), text.encode(), hashlib.sha256).hexdigest()

    def _seed_drugs(self):
        with self._tx() as c:
            c.executemany("INSERT OR IGNORE INTO drugs(name, uses) VALUES (?,0)", [(d,) for d in DRUGS_SEED])

    def _notify(self, row, is_recall, station):
        for cb in list(self.call_listeners):   # ex : le Hub diffuse l'appel à l'écran TV
            try:
                cb(row, is_recall, station)
            except Exception:
                pass

    def _tv_notify(self, ev):
        for cb in list(self.tv_listeners):
            try:
                cb(ev)
            except Exception:
                pass

    def _meta(self, key, default=""):
        r = self._one("SELECT value FROM meta WHERE key=?", (key,))
        return r["value"] if r else default

    def _set_meta(self, c, key, value):
        c.execute("INSERT INTO meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def _require(self, user_id, roles):
        """Contrôle d'accès par rôle côté base : une action n'est exécutée que pour un utilisateur actif du bon rôle."""
        sess = getattr(self._ctx, "uid", None)           # appel distant : l'identité vient du jeton JWT, jamais des arguments
        if sess is not None and user_id != sess:
            raise PermissionError("Identité de session différente de celle de la requête.")
        u = self._one("SELECT role, active FROM users WHERE id=?", (user_id,)) if user_id is not None else None
        if not u or not u["active"]:
            raise PermissionError("Session invalide : reconnectez-vous.")
        if u["role"] not in roles:
            raise PermissionError("Action non autorisée pour votre rôle.")
        return u["role"]

    def _require_fn(self, user_id, functions):
        self._require(user_id, ("labo",))
        fn = (self._one("SELECT function FROM users WHERE id=?", (user_id,)) or {}).get("function") or "LABORANTIN"
        if fn not in functions:
            raise PermissionError(f"Action réservée à la fonction : {', '.join(functions)}.")

    def _own_consultation(self, cid, user_id):
        self._require(user_id, ("medecin",))
        c = self._one("SELECT * FROM consultations WHERE id=?", (cid,))
        if not c or c["doctor_user_id"] != user_id:
            raise PermissionError("Cette consultation appartient à un autre médecin.")
        return c

    def _audit(self, c, adm_id, action, details, station):
        c.execute("INSERT INTO audit_log(admission_id,action,details,station,at) VALUES (?,?,?,?,?)",
                  (adm_id, action, json.dumps(details, ensure_ascii=False, default=str), station, now()))

    def _next_ticket(self, c, sid, svc):
        c.execute("INSERT OR IGNORE INTO counters(shift_id,service_code,last_number) VALUES (?,?,0)", (sid, svc["code"]))
        c.execute("UPDATE counters SET last_number=last_number+1 WHERE shift_id=? AND service_code=?", (sid, svc["code"]))
        n = c.execute("SELECT last_number FROM counters WHERE shift_id=? AND service_code=?", (sid, svc["code"])).fetchone()[0]
        return n, f"{svc['prefix']}-{n:03d}"

    # ---------- gardes / compteurs ----------
    def _current_shift(self, c, station=""):
        r = c.execute("SELECT id FROM shifts WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
        if r:
            return r["id"]
        return c.execute("INSERT INTO shifts(started_at, started_by) VALUES (?,?)", (now(), station)).lastrowid

    def current_shift(self, station=""):
        with self._tx() as c:
            return self._current_shift(c, station)

    def shift_info(self, shift_id):
        return self._one("SELECT * FROM shifts WHERE id=?", (shift_id,))

    def reset_shift(self, station="", user_id=None):
        """Remet tous les compteurs à zéro : ferme la garde en cours et en ouvre une nouvelle (agents d'accueil)."""
        self._require(user_id, ("accueil",))
        with self._tx() as c:
            c.execute("UPDATE shifts SET ended_at=? WHERE ended_at IS NULL", (now(),))
            sid = c.execute("INSERT INTO shifts(started_at, started_by) VALUES (?,?)", (now(), station)).lastrowid
            self._audit(c, None, "RESET_COUNTERS", {"new_shift": sid, "user": user_id}, station)
        self.auto_backup("fin de garde")
        return sid

    # ---------- utilisateurs ----------
    @staticmethod
    def _public_user(u):
        return {"id": u["id"], "last_name": u["last_name"], "first_name": u["first_name"], "role": u["role"],
                "specialty": u["specialty"] or "", "active": u["active"],
                "services": [s for s in (u.get("services") or "").split(",") if s],
                "function": u.get("function") or default_function(u["role"], [s for s in (u.get("services") or "").split(",") if s]),
                "has_signature": bool(u["signature_b64"] or u.get("sign_b64"))}

    def count_users(self):
        return self._one("SELECT COUNT(*) AS n FROM users WHERE active=1")["n"]

    def list_users(self, roles=None, active_only=True):
        sql, args = "SELECT * FROM users WHERE 1=1", []
        if active_only:
            sql += " AND active=1"
        if roles:
            sql += f" AND role IN ({','.join('?' * len(roles))})"; args += list(roles)
        return [self._public_user(u) for u in self._all(sql + " ORDER BY role, last_name, first_name", args)]

    @staticmethod
    def _resolve_function(function, services=()):
        """`function` = libellé officiel (liste fermée) ou, par compatibilité, un code d'espace (rôle). Retourne (rôle, fonction)."""
        if function in ROLE_OF:
            return ROLE_OF[function], function
        if function in ROLES:
            return function, default_function(function, services)
        raise ValueError("Fonction invalide : choisissez dans la liste officielle.")

    def create_user(self, last_name, first_name, function, specialty, pin, services=()):
        services = list(services if not isinstance(services, str) else services.split(","))
        role, fn = self._resolve_function(function, services)
        if not (last_name or "").strip() or not (first_name or "").strip():
            raise ValueError("Nom et prénom obligatoires.")
        if not re.fullmatch(r"\d{4}", pin or ""):
            raise ValueError("Le code PIN doit contenir exactement 4 chiffres.")
        if role == "medecin" and not services:
            services = DEFAULT_SERVICES.get(fn) or ["MG"]
        salt = secrets.token_hex(16)
        with self._tx() as c:
            return c.execute("""INSERT INTO users(last_name,first_name,role,function,specialty,pin_salt,pin_hash,created_at,services)
                                VALUES (?,?,?,?,?,?,?,?,?)""", (last_name.strip().upper(), first_name.strip(), role, fn, (specialty or "").strip(),
                                                                salt, _hash_pin(pin, salt), now(), ",".join(services))).lastrowid

    def update_user(self, user_id, fields):
        allowed = {k: v for k, v in fields.items() if k in ("last_name", "first_name", "role", "function", "specialty", "active", "services")}
        if "function" in allowed:
            allowed["role"], allowed["function"] = self._resolve_function(allowed["function"], allowed.get("services") or ())
        elif "role" in allowed and allowed["role"] not in ROLES:
            raise ValueError("Rôle invalide.")
        if "last_name" in allowed:
            allowed["last_name"] = allowed["last_name"].strip().upper()
        if "services" in allowed and not isinstance(allowed["services"], str):
            allowed["services"] = ",".join(allowed["services"])
        if not allowed:
            return
        with self._tx() as c:
            c.execute(f"UPDATE users SET {','.join(k + '=?' for k in allowed)} WHERE id=?", list(allowed.values()) + [user_id])

    def delete_user(self, user_id):
        """Suppression définitive possible seulement si le compte n'a laissé aucune trace (sinon : le désactiver)."""
        used = any(self._one(f"SELECT 1 AS x FROM {t} WHERE {col}=? LIMIT 1", (user_id,)) for t, col in (
            ("admissions", "created_by"), ("admissions", "called_user_id"), ("consultations", "doctor_user_id"),
            ("prescriptions", "doctor_user_id"), ("prescriptions", "dispensed_by"), ("radiology_requests", "doctor_user_id"),
            ("radiology_requests", "tech_user_id"), ("lab_requests", "doctor_user_id"), ("lab_requests", "tech_user_id"),
            ("results", "user_id")))
        if used:
            raise ValueError("Ce compte a un historique (consultations, tickets, résultats…) : désactivez-le plutôt que de le supprimer.")
        with self._tx() as c:
            c.execute("DELETE FROM users WHERE id=?", (user_id,))

    def reset_user_pin(self, user_id, pin):
        if not re.fullmatch(r"\d{4}", pin or ""):
            raise ValueError("Le code PIN doit contenir exactement 4 chiffres.")
        salt = secrets.token_hex(16)
        with self._tx() as c:
            c.execute("UPDATE users SET pin_salt=?, pin_hash=?, failed_count=0, locked_until=NULL WHERE id=?",
                      (salt, _hash_pin(pin, salt), user_id))

    def change_own_pin(self, user_id, old_pin, new_pin):
        res = self.verify_pin(user_id, old_pin)
        if not res["ok"]:
            return res
        self.reset_user_pin(user_id, new_pin)
        return {"ok": True}

    def verify_pin(self, user_id, pin):
        with self._tx() as c:
            u = c.execute("SELECT * FROM users WHERE id=? AND active=1", (user_id,)).fetchone()
            if not u:
                return {"ok": False, "error": "Utilisateur introuvable ou désactivé."}
            if u["locked_until"] and u["locked_until"] > now():
                return {"ok": False, "error": "Trop d'échecs : compte verrouillé 60 secondes."}
            if hmac.compare_digest(_hash_pin(pin or "", u["pin_salt"]), u["pin_hash"]):
                c.execute("UPDATE users SET failed_count=0, locked_until=NULL WHERE id=?", (user_id,))
                return {"ok": True, "user": self._public_user(dict(u))}
            n = u["failed_count"] + 1
            lock = (datetime.now() + timedelta(seconds=60)).strftime(FMT) if n >= 5 else None
            c.execute("UPDATE users SET failed_count=?, locked_until=? WHERE id=?", (0 if lock else n, lock, user_id))
            return {"ok": False, "error": "Compte verrouillé 60 secondes." if lock else f"Code PIN incorrect ({n}/5)."}

    def get_user(self, user_id):
        u = self._one("SELECT * FROM users WHERE id=?", (user_id,))
        if not u:
            return None
        d = self._public_user(u)
        d["signature_b64"], d["sign_b64"] = u["signature_b64"], u["sign_b64"]     # griffe (cachet) et signature
        return d

    def set_user_image(self, user_id, kind, b64):
        """kind = 'griffe' (cachet) ou 'signature' (signature manuscrite)."""
        if kind not in ("griffe", "signature"):
            raise ValueError("Type d'image invalide.")
        if b64 and len(b64) > 700_000:
            raise ValueError("Image trop volumineuse.")
        col = "signature_b64" if kind == "griffe" else "sign_b64"
        with self._tx() as c:
            c.execute(f"UPDATE users SET {col}=? WHERE id=?", (b64 or None, user_id))

    def set_signature(self, user_id, b64):
        self.set_user_image(user_id, "griffe", b64)

    # ---------- médicaments ----------
    def list_drug_names(self):
        return [r["name"] for r in self._all("SELECT name FROM drugs ORDER BY uses DESC, name")]

    def add_drug(self, name):
        name = (name or "").strip()
        if name:
            with self._tx() as c:
                c.execute("INSERT OR IGNORE INTO drugs(name,uses) VALUES (?,0)", (name,))
                c.execute("UPDATE drugs SET uses=uses+1 WHERE name=?", (name,))

    def import_drugs(self, names):
        """Import de la nomenclature (liste de libellés). Retourne le nombre de médicaments ajoutés."""
        clean = [n.strip() for n in names if isinstance(n, str) and n.strip()]
        with self._tx() as c:
            before = c.execute("SELECT COUNT(*) FROM drugs").fetchone()[0]
            c.executemany("INSERT OR IGNORE INTO drugs(name,uses) VALUES (?,0)", [(n,) for n in clean])
            return c.execute("SELECT COUNT(*) FROM drugs").fetchone()[0] - before

    # ---------- admissions ----------
    def get(self, adm_id):
        return self._one("SELECT * FROM admissions WHERE id=?", (adm_id,))

    def add_admission(self, d, station=""):
        """d = {last_name, first_name, parsed, gender, service_code, triage?, ident?, user_id}."""
        role = self._require(d.get("user_id"), ("accueil", "radio", "labo"))
        if role == "radio" and d["service_code"] != "RAD":
            raise PermissionError("Un manipulateur radio ne peut inscrire que pour la Radiologie.")
        if role == "labo" and d["service_code"] not in ("LAB", "LABP"):
            raise PermissionError("Le secrétariat du laboratoire ne peut émettre que des tickets de laboratoire.")
        svc = SERVICE_BY_CODE[d["service_code"]]
        p, last, first = d["parsed"], d["last_name"].strip(), d["first_name"].strip()
        full = f"{last.upper()} {first}".strip()
        with self._tx() as c:
            sid = self._current_shift(c, station)
            n, label = self._next_ticket(c, sid, svc)
            triage = d.get("triage") if svc["triage"] else None
            aid = c.execute(
                """INSERT INTO admissions(shift_id,service_code,ticket_number,ticket_label,full_name,name_norm,
                   birth_date,birth_year,gender,triage_level,created_at,station_name,last_name,first_name,created_by,patient_ident)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sid, svc["code"], n, label, full, norm_name(last, first), p["birth_date"], p["birth_year"],
                 d["gender"], triage, now(), station, last.upper(), first, d["user_id"], (d.get("ident") or "").strip() or None)).lastrowid
            if svc["code"] == "RAD":   # inscription directe en radiologie : apparaît dans la file du manipulateur
                c.execute("""INSERT INTO radiology_requests(uuid,source,admission_id,ticket_label,status,created_at,queue_ts)
                             VALUES (?,?,?,?,?,?,?)""", (uuid.uuid4().hex, "RECEPTION", aid, label, "PENDING", now(), now_us()))
            self._audit(c, aid, "CREATE", {"ticket": label, "user": d["user_id"]}, station)
        return self.get(aid)

    def update_admission(self, adm_id, f, station=""):
        """Correction d'erreur : le numéro/label du ticket ne change JAMAIS."""
        self._require(f.get("user_id"), ("accueil", "radio", "labo"))
        svc = SERVICE_BY_CODE[f["service_code"]]
        p, last, first = f["parsed"], f["last_name"].strip(), f["first_name"].strip()
        triage = f.get("triage") if svc["triage"] else None
        with self._tx() as c:
            old = self.get(adm_id)
            c.execute("""UPDATE admissions SET full_name=?, name_norm=?, last_name=?, first_name=?, birth_date=?, birth_year=?,
                         gender=?, service_code=?, triage_level=?, patient_ident=?, modified_at=?, modified_count=modified_count+1
                         WHERE id=?""",
                      (f"{last.upper()} {first}".strip(), norm_name(last, first), last.upper(), first, p["birth_date"],
                       p["birth_year"], f["gender"], svc["code"], triage, (f.get("ident") or "").strip() or None, now(), adm_id))
            self._audit(c, adm_id, "UPDATE", {"user": f.get("user_id"), "before": {k: old[k] for k in
                        ("full_name", "birth_date", "birth_year", "gender", "service_code", "triage_level")}}, station)
        return self.get(adm_id)

    def history(self, shift_id=None, search=""):
        sql, args = "SELECT * FROM admissions WHERE 1=1", []
        if shift_id:
            sql += " AND shift_id=?"; args.append(shift_id)
        if search:
            sql += " AND (full_name LIKE ? OR ticket_label LIKE ? OR patient_ident LIKE ?)"; args += [f"%{search}%"] * 3
        return self._all(sql + " ORDER BY created_at DESC, id DESC LIMIT 1000", args)

    def stats(self, shift_id):
        q = "FROM admissions WHERE shift_id=? AND status!='CANCELLED'"
        total = self._one(f"SELECT COUNT(*) AS n {q}", (shift_id,))["n"]
        tri = {r["triage_level"]: r["n"] for r in self._all(
            f"SELECT triage_level, COUNT(*) AS n {q} AND triage_level IS NOT NULL GROUP BY triage_level", (shift_id,))}
        svc = {r["service_code"]: r["n"] for r in self._all(f"SELECT service_code, COUNT(*) AS n {q} GROUP BY service_code", (shift_id,))}
        return {"total": total, "ROUGE": tri.get("ROUGE", 0), "ORANGE": tri.get("ORANGE", 0),
                "VERT": tri.get("VERT", 0), "by_service": svc}

    # ---------- patients récurrents (information uniquement) ----------
    def find_revisit(self, last_name, first_name, gender, parsed, hours, exclude_id=None):
        since = (datetime.now() - timedelta(hours=hours)).strftime(FMT)
        exact = 1 if parsed.get("birth_date") else 0
        sql = """SELECT * FROM admissions WHERE name_norm=:n AND gender=:g AND created_at>=:since AND status!='CANCELLED'
                 AND (birth_year=:y OR (ABS(birth_year-:y)<=1 AND (birth_date IS NULL OR :exact=0)))"""
        args = {"n": norm_name(last_name, first_name), "g": gender, "since": since, "y": parsed["birth_year"], "exact": exact}
        if exclude_id:
            sql += " AND id!=:ex"; args["ex"] = exclude_id
        return self._one(sql + " ORDER BY created_at DESC LIMIT 1", args)

    # ---------- postes d'appel (médecins, laboratoire) ----------
    def queue(self, services, revisit_hours=72):
        """File d'attente par priorité ; `recurrent`=1 si le patient est déjà venu dans les `revisit_hours` heures."""
        if not services:
            return []
        ph = ",".join("?" * len(services))
        return self._all(
            f"""SELECT a.*, EXISTS(SELECT 1 FROM admissions b WHERE b.name_norm=a.name_norm AND b.gender=a.gender
                   AND ABS(b.birth_year-a.birth_year)<=1 AND b.id!=a.id AND b.status!='CANCELLED'
                   AND b.id<a.id AND b.created_at>=datetime(a.created_at, ?)) AS recurrent
                FROM admissions a WHERE a.status='WAITING' AND a.service_code IN ({ph})
                ORDER BY CASE a.triage_level WHEN 'ROUGE' THEN 0 WHEN 'ORANGE' THEN 1 ELSE 2 END, a.created_at, a.id""",
            [f"-{int(revisit_hours)} hours"] + list(services))

    def current_called(self, station, user_id):
        """Patient en cours de ce médecin (isolé par compte : plusieurs médecins peuvent se relayer sur le même poste)."""
        return self._one("SELECT * FROM admissions WHERE status='CALLED' AND called_user_id=? ORDER BY called_at DESC LIMIT 1", (user_id,))

    def call_next(self, services, station, user_id, room=None):
        """Appelle le patient prioritaire ; `room` = libellé du bureau affiché sur l'écran TV (jamais de nom de patient)."""
        self._require(user_id, ("medecin", "labo", "soins"))
        q = self.queue(services)
        if not q:
            return None
        nxt = q[0]
        with self._tx() as c:
            c.execute("UPDATE admissions SET status='DONE', finished_at=? WHERE status='CALLED' AND called_user_id=?", (now(), user_id))
            c.execute("UPDATE admissions SET status='CALLED', called_at=?, called_by=?, called_user_id=? WHERE id=?",
                      (now(), station, user_id, nxt["id"]))
            c.execute("INSERT INTO calls(admission_id,called_at,station) VALUES (?,?,?)", (nxt["id"], now(), room or station))
        row = self.get(nxt["id"])
        self._notify(row, False, room or station)
        return row

    def recall(self, adm_id, station, user_id, room=None):
        self._require(user_id, ("medecin", "labo", "soins"))
        with self._tx() as c:
            c.execute("INSERT INTO calls(admission_id,called_at,station,is_recall) VALUES (?,?,?,1)", (adm_id, now(), room or station))
        row = self.get(adm_id)
        self._notify(row, True, room or station)
        return row

    def finish(self, adm_id, user_id):
        self._require(user_id, ("medecin", "labo", "soins"))
        with self._tx() as c:
            c.execute("UPDATE admissions SET status='DONE', finished_at=? WHERE id=?", (now(), adm_id))

    def release_patient(self, adm_id, user_id):
        """Le patient retourne en file d'attente (changement de médecin / de garde) ; la consultation du médecin est marquée interrompue."""
        self._require(user_id, ("medecin", "labo", "soins"))
        with self._tx() as c:
            c.execute("""UPDATE admissions SET status='WAITING', called_at=NULL, called_by=NULL, called_user_id=NULL,
                         handover_note=NULL, handover_from=NULL, handover_at=NULL WHERE id=? AND called_user_id=?""", (adm_id, user_id))
            c.execute("UPDATE consultations SET ended_at=?, outcome='INTERRUPTED' WHERE admission_id=? AND doctor_user_id=? AND ended_at IS NULL",
                      (now(), adm_id, user_id))

    # ---------- consultation ----------
    def start_consultation(self, admission_id, user_id, station=""):
        self._require(user_id, ("medecin",))
        with self._tx() as c:
            r = c.execute("SELECT * FROM consultations WHERE admission_id=? AND doctor_user_id=? AND ended_at IS NULL",
                          (admission_id, user_id)).fetchone()
            if not r:
                cid = c.execute("INSERT INTO consultations(admission_id,doctor_user_id,station,started_at) VALUES (?,?,?,?)",
                                (admission_id, user_id, station, now())).lastrowid
                r = c.execute("SELECT * FROM consultations WHERE id=?", (cid,)).fetchone()
            return dict(r)

    def close_consultation(self, cid, notes="", diagnosis="", user_id=None):
        cons = self._own_consultation(cid, user_id)
        with self._tx() as c:
            c.execute("UPDATE consultations SET ended_at=?, notes=?, diagnosis=?, outcome='CLOSED' WHERE id=?", (now(), self._enc(notes), self._enc(diagnosis), cid))
            c.execute("UPDATE admissions SET status='DONE', finished_at=COALESCE(finished_at,?) WHERE id=?", (now(), cons["admission_id"]))
            c.execute("DELETE FROM drafts WHERE admission_id=?", (cons["admission_id"],))
        d = self.consultation_dossier(cid)
        if self.sync_enabled:                                  # file de synchronisation hors-ligne (FHIR)
            from fhir import consultation_bundle
            self._outbox_add("consultation", cid, consultation_bundle(d))
        return d

    def consultation_dossier(self, cid):
        cons = self._one("SELECT * FROM consultations WHERE id=?", (cid,))
        doc = self._one("SELECT * FROM users WHERE id=?", (cons["doctor_user_id"],))
        rx = [self._rx(r["uuid"]) for r in self._all("SELECT uuid FROM prescriptions WHERE consultation_id=?", (cid,))]
        return {"consultation": cons, "patient": self.get(cons["admission_id"]),
                "doctor": self._public_user(doc) if doc else None, "prescriptions": rx,
                "radiology": self._all(_RADIO_SELECT + " WHERE r.consultation_id=? ORDER BY r.id", (cid,)),
                "lab_requests": self._labs("WHERE l.consultation_id=?", (cid,))}

    # ---------- ordonnance numérique ----------
    def _rx(self, uid):
        r = self._one("SELECT * FROM prescriptions WHERE uuid=?", (uid,))
        if not r:
            return None
        r["items"] = json.loads(r["items_json"])
        r["qr_text"] = f"SDEM1{r['uuid']}{r['sig']}"
        r["number"] = f"{r['created_at'][:4]}{r['id']:06d}"          # N° d'ordonnance (10 chiffres) = code-barres
        r["patient"] = self.get(r["admission_id"])
        u = self._one("SELECT * FROM users WHERE id=?", (r["doctor_user_id"],))
        r["doctor"] = self._public_user(u) if u else None
        return r

    def create_prescription(self, consultation_id, items, notes="", user_id=None):
        cons = self._own_consultation(consultation_id, user_id)
        items = [{"drug": (i.get("drug") or "").strip(), "dosage": (i.get("dosage") or "").strip(),
                  "duration": (i.get("duration") or "").strip()} for i in items if (i.get("drug") or "").strip()]
        if not items:
            raise ValueError("L'ordonnance est vide.")
        adm = self.get(cons["admission_id"])
        uid, created = uuid.uuid4().hex, now()
        canonical = json.dumps({"uuid": uid, "patient": {"nom": adm["last_name"], "prenom": adm["first_name"],
                                "annee": adm["birth_year"], "genre": adm["gender"]}, "doctor": user_id,
                                "date": created, "items": items, "notes": notes or ""}, sort_keys=True, ensure_ascii=False)
        chash = hashlib.sha256(canonical.encode()).hexdigest()
        with self._tx() as c:
            c.execute("""INSERT INTO prescriptions(uuid,consultation_id,admission_id,doctor_user_id,items_json,notes,
                         canonical,content_hash,sig,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                      (uid, consultation_id, adm["id"], user_id, self._enc(json.dumps(items, ensure_ascii=False)), self._enc(notes or ""),
                       self._enc(canonical), chash, self._sign(uid + chash)[:16], created))
        for i in items:
            self.add_drug(i["drug"])
        return self._rx(uid)

    def get_prescription(self, uid, user_id=None):
        self._require(user_id, ("medecin", "pharmacie"))
        return self._rx(uid)

    def send_to_pharmacy(self, uid, user_id=None):
        self._require(user_id, ("medecin",))
        rx = self._rx(uid)
        if not rx or rx["doctor_user_id"] != user_id:
            raise PermissionError("Cette ordonnance appartient à un autre médecin.")
        if rx["status"] != "CREATED":
            return rx
        light = {"uuid": uid, "number": rx["number"], "qr_text": rx["qr_text"], "date": rx["created_at"],
                 "patient": {"nom": rx["patient"]["last_name"], "prenom": rx["patient"]["first_name"],
                             "age": age_from_row(rx["patient"]), "genre": rx["patient"]["gender"]},
                 "doctor": f"{rx['doctor']['last_name']} {rx['doctor']['first_name']}" if rx["doctor"] else "",
                 "items": rx["items"], "notes": rx["notes"]}
        with self._tx() as c:
            c.execute("UPDATE prescriptions SET status='SENT', sent_at=? WHERE uuid=?", (now(), uid))
            c.execute("INSERT INTO transit_queue(channel,ref_uuid,payload,created_at) VALUES ('pharmacie',?,?,?)",
                      (uid, self._enc(json.dumps(light, ensure_ascii=False)), now()))
        return self._rx(uid)

    def pharmacy_queue(self, user_id=None):
        self._require(user_id, ("pharmacie",))
        out = []
        for r in self._all("SELECT * FROM transit_queue WHERE channel='pharmacie' AND status='PENDING' ORDER BY id"):
            p = json.loads(r["payload"]); p["transit_id"] = r["id"]; out.append(p)
        return out

    def pharmacy_lookup(self, text, user_id=None):
        self._require(user_id, ("pharmacie",))
        t = (text or "").strip()
        m = re.fullmatch(r"SDEM1([0-9a-fA-F]{32})([0-9a-fA-F]{16})", t)
        if m:
            uid, sig = m.group(1).lower(), m.group(2).lower()
            rx = self._rx(uid)
            if not rx:
                return {"found": False, "authentic": False, "reason": "QR inconnu de ce système (ordonnance d'un autre établissement ou falsifiée)."}
            ok_sig = hmac.compare_digest(self._sign(uid + rx["content_hash"])[:16], sig)
            ok_hash = hashlib.sha256(rx["canonical"].encode()).hexdigest() == rx["content_hash"]
            reason = "" if (ok_sig and ok_hash) else "Signature du QR invalide ou contenu altéré."
            return {"found": True, "authentic": ok_sig and ok_hash, "reason": reason, "rx": rx}
        if re.fullmatch(r"(20\d{2})(\d{6})", t):                     # code-barres : N° d'ordonnance
            row = self._one("SELECT uuid FROM prescriptions WHERE id=? AND substr(created_at,1,4)=?", (int(t[4:]), t[:4]))
            if row:
                return {"found": True, "authentic": None, "rx": self._rx(row["uuid"]),
                        "reason": "Code-barres : ordonnance retrouvée, authenticité non vérifiable — scannez le QR Code."}
        elif re.fullmatch(r"[0-9a-fA-F]{8,32}", t):
            rows = self._all("SELECT uuid FROM prescriptions WHERE uuid LIKE ?", (t.lower() + "%",))
            if len(rows) == 1:
                return {"found": True, "authentic": None, "rx": self._rx(rows[0]["uuid"]),
                        "reason": "Saisie manuelle : authenticité non vérifiable, scannez le QR Code."}
        return {"found": False, "authentic": False, "reason": "Code illisible ou ordonnance introuvable."}

    def pharmacy_dispense(self, uid, user_id=None):
        self._require(user_id, ("pharmacie",))
        rx = self._rx(uid)
        if not rx:
            return {"ok": False, "error": "Ordonnance introuvable."}
        if rx["status"] == "DISPENSED":
            return {"ok": False, "error": f"Déjà délivrée le {rx['dispensed_at']}."}
        with self._tx() as c:
            c.execute("UPDATE prescriptions SET status='DISPENSED', dispensed_at=?, dispensed_by=? WHERE uuid=?", (now(), user_id, uid))
            c.execute("UPDATE transit_queue SET status='DONE' WHERE channel='pharmacie' AND ref_uuid=?", (uid,))
        return {"ok": True}

    # ---------- radiologie ----------
    def _radio_row(self, rid):
        return self._one(_RADIO_SELECT + " WHERE r.id=?", (rid,))

    def create_radio_request(self, consultation_id, exam_type, region, side, clinical_info, instructions, urgent, user_id, station=""):
        cons = self._own_consultation(consultation_id, user_id)
        with self._tx() as c:
            sid = self._current_shift(c, station)
            _, label = self._next_ticket(c, sid, SERVICE_BY_CODE["RAD"])
            rid = c.execute("""INSERT INTO radiology_requests(uuid,source,consultation_id,admission_id,doctor_user_id,ticket_label,
                               exam_type,region,side,clinical_info,instructions,urgent,status,created_at,queue_ts)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (uuid.uuid4().hex, "MEDECIN", consultation_id, cons["admission_id"], user_id, label, exam_type,
                             region, side, self._enc(clinical_info), self._enc(instructions), 1 if urgent else 0, "PENDING", now(), now_us())).lastrowid
        return self._radio_row(rid)

    def radio_queue(self, user_id=None):
        self._require(user_id, ("radio",))
        return self._all(_RADIO_SELECT + " WHERE r.status IN ('PENDING','CALLED') ORDER BY r.urgent DESC, r.queue_ts, r.id")

    def radio_awaiting(self, user_id=None):
        self._require(user_id, ("radio",))
        return self._all(_RADIO_SELECT + " WHERE r.status='AWAITING_PRINT' ORDER BY r.done_at")

    def radio_call_next(self, station, user_id=None, room=None):
        self._require(user_id, ("radio",))
        with self._tx() as c:   # un patient appelé mais non validé retourne dans la file (reporté)
            c.execute("UPDATE radiology_requests SET status='PENDING', queue_ts=?, skipped=skipped+1 WHERE status='CALLED' AND called_by=?",
                      (now_us(), station))
            r = c.execute("SELECT id FROM radiology_requests WHERE status='PENDING' ORDER BY urgent DESC, queue_ts, id LIMIT 1").fetchone()
            if not r:
                return None
            c.execute("UPDATE radiology_requests SET status='CALLED', called_at=?, called_by=?, tech_user_id=? WHERE id=?",
                      (now(), station, user_id, r["id"]))
            rid = r["id"]
        row = self._radio_row(rid)
        self._notify({"ticket_label": row["ticket_label"], "service_code": "RAD"}, False, room or station)
        return row

    def radio_recall(self, request_id, station, user_id=None, room=None):
        self._require(user_id, ("radio",))
        row = self._radio_row(request_id)
        self._notify({"ticket_label": row["ticket_label"], "service_code": "RAD"}, True, room or station)
        return row

    def radio_validate(self, request_id, status, note="", user_id=None):
        self._require(user_id, ("radio",))
        if status not in ("DONE", "AWAITING_PRINT"):
            raise ValueError("Statut invalide.")
        with self._tx() as c:
            r = c.execute("SELECT * FROM radiology_requests WHERE id=?", (request_id,)).fetchone()
            c.execute("UPDATE radiology_requests SET status=?, done_at=COALESCE(done_at,?), tech_user_id=?, result_note=? WHERE id=?",
                      (status, now(), user_id, self._enc(note) if note else r["result_note"], request_id))
            if r["source"] == "RECEPTION" and r["admission_id"]:
                c.execute("UPDATE admissions SET status='DONE', finished_at=COALESCE(finished_at,?) WHERE id=?", (now(), r["admission_id"]))
        return self._radio_row(request_id)

    def radio_requests_for_doctor(self, user_id, hours=24):
        self._require(user_id, ("medecin",))
        since = (datetime.now() - timedelta(hours=hours)).strftime(FMT)
        return self._all(_RADIO_SELECT + " WHERE r.doctor_user_id=? AND r.created_at>=? ORDER BY r.id DESC", (user_id, since))

    def radio_for_consultation(self, cid, user_id=None):
        self._require(user_id, ("medecin", "radio"))
        return self._all(_RADIO_SELECT + " WHERE r.consultation_id=? ORDER BY r.id", (cid,))

    # ---------- laboratoire ----------
    def _labs(self, where="", args=()):
        rows = self._all("""SELECT l.*, a.last_name, a.first_name, a.full_name, a.birth_year, a.birth_date, a.gender,
            u.last_name AS doc_last, u.first_name AS doc_first,
            (SELECT COUNT(*) FROM results rs WHERE rs.kind='lab' AND rs.request_id=l.id) AS n_results
            FROM lab_requests l LEFT JOIN admissions a ON a.id=l.admission_id LEFT JOIN users u ON u.id=l.doctor_user_id """
                         + where + " ORDER BY l.id", args)
        for r in rows:
            r["items"] = json.loads(r.pop("items_json"))
        return rows

    def create_lab_request(self, consultation_id, items, clinical_info="", urgent=False, user_id=None):
        cons = self._own_consultation(consultation_id, user_id)
        items = [i.strip() for i in items if i and i.strip()]
        if not items:
            raise ValueError("Sélectionnez au moins une analyse.")
        uid = uuid.uuid4().hex
        with self._tx() as c:
            sid = self._current_shift(c, "")
            _, label = self._next_ticket(c, sid, {"code": "BIO", "prefix": "BIO"})
            lid = c.execute("""INSERT INTO lab_requests(uuid,consultation_id,admission_id,doctor_user_id,items_json,clinical_info,
                               created_at,status,ticket_label,urgent,queue_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                            (uid, consultation_id, cons["admission_id"], user_id, self._enc(json.dumps(items, ensure_ascii=False)),
                             self._enc(clinical_info or ""), now(), "PENDING", label, 1 if urgent else 0, now_us())).lastrowid
        return self._labs("WHERE l.id=?", (lid,))[0]

    def lab_queue(self, user_id=None):
        self._require(user_id, ("labo",))
        rows = self._labs("WHERE l.status IN ('PENDING','IN_PROGRESS')")
        return sorted(rows, key=lambda r: (-r["urgent"], r["queue_ts"] or "", r["id"]))

    def lab_start(self, request_id, station, user_id=None):
        self._require(user_id, ("labo",))
        with self._tx() as c:
            c.execute("UPDATE lab_requests SET status='IN_PROGRESS', tech_user_id=? WHERE id=? AND status='PENDING'", (user_id, request_id))
        return self._labs("WHERE l.id=?", (request_id,))[0]

    def lab_validate(self, request_id, note="", user_id=None):
        self._require_fn(user_id, ("LABORANTIN",))
        with self._tx() as c:
            c.execute("UPDATE lab_requests SET status='DONE', done_at=?, tech_user_id=? WHERE id=?", (now(), user_id, request_id))
        return self._labs("WHERE l.id=?", (request_id,))[0]

    def lab_requests_for_doctor(self, user_id, hours=24):
        self._require(user_id, ("medecin",))
        since = (datetime.now() - timedelta(hours=hours)).strftime(FMT)
        return sorted(self._labs("WHERE l.doctor_user_id=? AND l.created_at>=?", (user_id, since)), key=lambda r: -r["id"])

    def lab_for_consultation(self, cid, user_id=None):
        self._require(user_id, ("medecin", "labo", "soins"))
        return self._labs("WHERE l.consultation_id=?", (cid,))

    # ---------- résultats : cliché / compte rendu (radio) et résultats (labo) renvoyés au médecin demandeur ----------
    def add_result(self, kind, request_id, filename, mime, data_b64, report_text, user_id=None):
        if kind == "lab":
            self._require_fn(user_id, ("LABORANTIN",))
        else:
            self._require(user_id, ("radio",))
        if kind not in ("radio", "lab"):
            raise ValueError("Type de résultat invalide.")
        if data_b64 and len(data_b64) > 12_000_000:
            raise ValueError("Fichier trop volumineux (maximum environ 9 Mo).")
        if not data_b64 and not (report_text or "").strip():
            raise ValueError("Joignez un fichier ou saisissez un compte rendu.")
        with self._tx() as c:
            return c.execute("""INSERT INTO results(kind,request_id,filename,mime,data_b64,report_text,created_at,user_id)
                                VALUES (?,?,?,?,?,?,?,?)""", (kind, request_id, filename, mime, self._enc(data_b64) if data_b64 else None,
                                                              self._enc((report_text or "").strip()), now(), user_id)).lastrowid

    def list_results(self, kind, request_id, user_id=None):
        self._require(user_id, ("medecin", "radio", "labo"))
        return self._all("""SELECT r.id, r.filename, r.mime, r.report_text, r.created_at, LENGTH(r.data_b64) AS size,
                            u.last_name AS tech_last, u.first_name AS tech_first FROM results r LEFT JOIN users u ON u.id=r.user_id
                            WHERE r.kind=? AND r.request_id=? ORDER BY r.id""", (kind, request_id))

    def get_result(self, result_id, user_id=None):
        self._require(user_id, ("medecin", "radio", "labo"))
        return self._one("SELECT * FROM results WHERE id=?", (result_id,))

    # ---------- recherche & archives patients (DPI) ----------
    def search_patients(self, query, user_id=None):
        """Recherche par nom, prénom, date de naissance (jj/mm/aaaa ou année) ou N° d'identification."""
        self._require(user_id, ("medecin", "accueil"))
        q = (query or "").strip()
        if len(q) < 2:
            return []
        where, args = [], []
        m = re.fullmatch(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", q)
        if m:
            try:
                d, mo, y = map(int, m.groups())
                where.append("birth_date=?"); args.append(date(y, mo, d).isoformat())
            except ValueError:
                return []
        elif re.fullmatch(r"(19|20)\d{2}", q):
            where.append("birth_year=?"); args.append(int(q))
        elif any(ch.isdigit() for ch in q) and " " not in q:
            where.append("patient_ident LIKE ?"); args.append(f"%{q}%")
        else:
            toks = norm_name(q).split()
            if not toks:
                return []
            for t in toks:
                where.append("name_norm LIKE ?"); args.append(f"%{t}%")
        rows = self._all(f"SELECT * FROM admissions WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT 400", args)
        groups = {}
        for r in rows:
            key = ("ID", r["patient_ident"]) if r["patient_ident"] else (r["name_norm"], r["gender"], r["birth_year"])
            g = groups.setdefault(key, {"admission_id": r["id"], "display": display_name(r), "birth": birth_text(r),
                                        "gender": r["gender"], "ident": r["patient_ident"] or "", "visits": 0,
                                        "last_visit": r["created_at"], "last_service": r["service_code"]})
            g["visits"] += 1
        return list(groups.values())

    def patient_record(self, admission_id, user_id=None, station=""):
        """Dossier patient informatisé. Médecin : historique clinique complet. Accueil : identité et passages seulement."""
        role = self._require(user_id, ("medecin", "accueil"))
        a = self.get(admission_id)
        if not a:
            raise ValueError("Dossier introuvable.")
        rows = self._all("""SELECT * FROM admissions WHERE (patient_ident IS NOT NULL AND patient_ident=:i)
                            OR (name_norm=:n AND gender=:g AND ABS(birth_year-:y)<=1) ORDER BY created_at DESC""",
                         {"i": a["patient_ident"], "n": a["name_norm"], "g": a["gender"], "y": a["birth_year"]})
        with self._tx() as c:
            self._audit(c, admission_id, "DPI_VIEW", {"user": user_id, "level": role}, station)
        visits = []
        for r in rows:
            v = {"admission": r}
            if role == "medecin":
                v["consultations"] = self._all("""SELECT c.*, u.last_name AS doc_last, u.first_name AS doc_first FROM consultations c
                                                  LEFT JOIN users u ON u.id=c.doctor_user_id WHERE c.admission_id=? ORDER BY c.id""", (r["id"],))
                v["prescriptions"] = [self._rx(x["uuid"]) for x in self._all("SELECT uuid FROM prescriptions WHERE admission_id=? ORDER BY id", (r["id"],))]
                v["lab_requests"] = self._labs("WHERE l.admission_id=?", (r["id"],))
                v["radiology"] = self._all(_RADIO_SELECT + " WHERE r.admission_id=? ORDER BY r.id", (r["id"],))
                v["vitals"] = self._vitals(r["id"])
            visits.append(v)
        return {"level": role, "patient": {"display": display_name(a), "birth": birth_text(a), "gender": a["gender"],
                                           "ident": a["patient_ident"] or ""}, "visits": visits}

    # ---------- constantes vitales & orientation (poste Soins & Triage) ----------
    _TENSION = {"mmHg": (40, 300, 20, 200), "cmHg": (4, 30, 2, 20)}
    _GLYC = {"g/L": (0.1, 10), "mmol/L": (0.5, 55)}

    @staticmethod
    def _num(v, label):
        try:
            return float(str(v).replace(",", "."))
        except ValueError:
            raise ValueError(f"{label} : valeur numérique attendue.")

    def _vitals(self, adm_id):
        out = []
        for r in self._all("""SELECT v.id, v.recorded_at, v.vitals_json, u.last_name, u.first_name, u.function FROM vitals v
                              LEFT JOIN users u ON u.id=v.user_id WHERE v.admission_id=? ORDER BY v.id DESC""", (adm_id,)):
            d = json.loads(r.pop("vitals_json")); d.update(r); out.append(d)
        return out

    def record_vitals(self, adm_id, data, user_id=None):
        """Enregistre tension, glycémie, température (+ remarque) dans le dossier. Contrôle de plausibilité uniquement (pas d'interprétation clinique)."""
        self._require(user_id, ("soins", "medecin"))
        v = {}
        if str(data.get("sys", "")).strip() or str(data.get("dia", "")).strip():
            unit = data.get("tension_unit", "mmHg")
            if unit not in self._TENSION:
                raise ValueError("Unité de tension invalide.")
            smin, smax, dmin, dmax = self._TENSION[unit]
            sys_, dia = self._num(data.get("sys"), "Tension systolique"), self._num(data.get("dia"), "Tension diastolique")
            if not (smin <= sys_ <= smax and dmin <= dia <= dmax and dia < sys_):
                raise ValueError(f"Tension impossible pour l'unité {unit} : vérifiez la saisie.")
            v.update(sys=round(sys_, 1), dia=round(dia, 1), tension_unit=unit)
        if str(data.get("glyc", "")).strip():
            unit = data.get("glyc_unit", "g/L")
            if unit not in self._GLYC:
                raise ValueError("Unité de glycémie invalide.")
            g = self._num(data["glyc"], "Glycémie")
            if not (self._GLYC[unit][0] <= g <= self._GLYC[unit][1]):
                raise ValueError(f"Glycémie impossible pour l'unité {unit} : vérifiez la saisie.")
            v.update(glyc=round(g, 2), glyc_unit=unit)
        if str(data.get("temp", "")).strip():
            t = self._num(data["temp"], "Température")
            if not 30 <= t <= 45:
                raise ValueError("Température impossible (30 à 45 °C) : vérifiez la saisie.")
            v["temp"] = round(t, 1)
        if (data.get("note") or "").strip():
            v["note"] = data["note"].strip()[:300]
        if not v:
            raise ValueError("Saisissez au moins une constante.")
        with self._tx() as c:
            vid = c.execute("INSERT INTO vitals(admission_id,user_id,recorded_at,vitals_json) VALUES (?,?,?,?)",
                            (adm_id, user_id, now(), self._enc(json.dumps(v, ensure_ascii=False)))).lastrowid
            self._audit(c, adm_id, "VITALS", {"user": user_id}, "")
        return next(x for x in self._vitals(adm_id) if x["id"] == vid)

    def vitals_for_admission(self, adm_id, user_id=None):
        self._require(user_id, ("soins", "medecin", "coord_para"))
        return self._vitals(adm_id)

    def orient_patient(self, adm_id, service_code, triage, user_id=None):
        """Après les constantes : oriente le patient vers la file d'un service médical avec son niveau de tri (le ticket garde son numéro)."""
        self._require(user_id, ("soins",))
        if service_code not in CONSULT_SERVICES:
            raise ValueError("Service d'orientation invalide.")
        svc = SERVICE_BY_CODE[service_code]
        if svc["triage"] and triage not in ("VERT", "ORANGE", "ROUGE"):
            raise ValueError("Choisissez le niveau de tri (vert / orange / rouge).")
        with self._tx() as c:
            a = c.execute("SELECT * FROM admissions WHERE id=?", (adm_id,)).fetchone()
            if not a or a["status"] in ("DONE", "CANCELLED"):
                raise ValueError("Patient introuvable ou déjà pris en charge.")
            c.execute("""UPDATE admissions SET service_code=?, triage_level=?, status='WAITING', called_at=NULL, called_by=NULL, called_user_id=NULL,
                         handover_note=NULL, handover_from=NULL, handover_at=NULL WHERE id=?""",
                      (service_code, triage if svc["triage"] else None, adm_id))
            c.execute("DELETE FROM drafts WHERE admission_id=? AND kind='soins'", (adm_id,))
            self._audit(c, adm_id, "ORIENT", {"from": a["service_code"], "to": service_code, "triage": triage, "user": user_id}, "")
        return self.get(adm_id)

    # ---------- vues globales des coordinateurs ----------
    def _coord_scope(self, user_id):
        role = self._require(user_id, ("coord_med", "coord_para"))
        return role, (["SOINS"] if role == "coord_para" else list(CONSULT_SERVICES))

    def coord_overview(self, user_id=None):
        """Vue globale multi-services de la garde en cours : files, appels, urgences, temps d'attente, relèves en cours."""
        role, scope = self._coord_scope(user_id)
        sh = self._one("SELECT id FROM shifts WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1")
        rows = self._all(f"SELECT * FROM admissions WHERE shift_id=? AND service_code IN ({','.join('?' * len(scope))}) AND status!='CANCELLED'",
                         [sh["id"] if sh else -1] + scope)
        by = {c: {"code": c, "waiting": 0, "called": 0, "done": 0, "red": 0, "oldest_wait": 0, "avg_wait": None, "_w": []} for c in scope}
        waiting, handovers, ref = [], 0, datetime.now()
        for r in rows:
            b = by[r["service_code"]]
            created = datetime.strptime(r["created_at"], FMT)
            if r["status"] == "WAITING":
                m = int((ref - created).total_seconds() // 60)
                b["waiting"] += 1; b["oldest_wait"] = max(b["oldest_wait"], m); b["red"] += r["triage_level"] == "ROUGE"
                waiting.append({"id": r["id"], "ticket_label": r["ticket_label"], "service_code": r["service_code"], "display": display_name(r),
                                "age": age_from_row(r), "triage_level": r["triage_level"], "wait_min": m})
            elif r["status"] == "CALLED":
                b["called"] += 1; handovers += 1 if r["handover_at"] else 0
            elif r["status"] == "DONE":
                b["done"] += 1
            if r["called_at"]:
                b["_w"].append((datetime.strptime(r["called_at"], FMT) - created).total_seconds() / 60)
        for b in by.values():
            w = b.pop("_w"); b["avg_wait"] = round(sum(w) / len(w), 1) if w else None
        order = {"ROUGE": 0, "ORANGE": 1}
        waiting.sort(key=lambda x: (order.get(x["triage_level"], 2), -x["wait_min"]))
        return {"role": role, "scope": scope, "by_service": list(by.values()), "waiting": waiting, "handovers": handovers, "total": len(rows)}

    def reassign_admission(self, adm_id, new_service, user_id=None):
        """Le coordinateur réoriente un patient EN ATTENTE vers un autre service (le ticket garde son numéro)."""
        self._coord_scope(user_id)
        if new_service not in CONSULT_SERVICES and new_service != "SOINS":
            raise ValueError("Service invalide.")
        svc = SERVICE_BY_CODE[new_service]
        with self._tx() as c:
            a = c.execute("SELECT * FROM admissions WHERE id=?", (adm_id,)).fetchone()
            if not a or a["status"] != "WAITING":
                raise ValueError("Seul un patient en attente peut être réorienté.")
            c.execute("UPDATE admissions SET service_code=?, triage_level=? WHERE id=?",
                      (new_service, a["triage_level"] if svc["triage"] else None, adm_id))
            self._audit(c, adm_id, "REASSIGN", {"from": a["service_code"], "to": new_service, "user": user_id}, "")
        return self.get(adm_id)

    # ---------- relève de garde : patient réservé pour un confrère + brouillons ----------
    def save_draft(self, adm_id, kind, data, user_id=None):
        self._require(user_id, ("medecin", "soins", "labo"))
        with self._tx() as c:
            c.execute("""INSERT INTO drafts(admission_id,user_id,kind,data_json,updated_at) VALUES (?,?,?,?,?)
                         ON CONFLICT(admission_id,user_id,kind) DO UPDATE SET data_json=excluded.data_json, updated_at=excluded.updated_at""",
                      (adm_id, user_id, kind, self._enc(json.dumps(data, ensure_ascii=False)), now()))

    def get_draft(self, adm_id, kind, user_id=None):
        self._require(user_id, ("medecin", "soins", "labo"))
        r = self._one("SELECT data_json FROM drafts WHERE admission_id=? AND user_id=? AND kind=?", (adm_id, user_id, kind))
        return json.loads(r["data_json"]) if r else None

    def delete_draft(self, adm_id, kind, user_id=None):
        self._require(user_id, ("medecin", "soins", "labo"))
        with self._tx() as c:
            c.execute("DELETE FROM drafts WHERE admission_id=? AND user_id=? AND kind=?", (adm_id, user_id, kind))

    def handover_start(self, adm_id, note="", user_id=None):
        """Relève de garde : le patient en cours est réservé (hors file d'attente) jusqu'à reprise par un confrère de même rôle."""
        self._require(user_id, ("medecin", "soins", "labo"))
        with self._tx() as c:
            a = c.execute("SELECT * FROM admissions WHERE id=?", (adm_id,)).fetchone()
            if not a or a["status"] != "CALLED" or a["called_user_id"] != user_id:
                raise ValueError("Ce patient n'est pas en cours avec vous.")
            c.execute("UPDATE admissions SET called_user_id=NULL, handover_from=?, handover_at=?, handover_note=? WHERE id=?",
                      (user_id, now(), (note or "").strip()[:300], adm_id))
            self._audit(c, adm_id, "HANDOVER_START", {"user": user_id}, "")

    def handover_list(self, services, user_id=None):
        role = self._require(user_id, ("medecin", "soins", "labo"))
        if not services:
            return []
        return self._all(f"""SELECT a.*, u.last_name AS from_last, u.first_name AS from_first, u.function AS from_function FROM admissions a
                             JOIN users u ON u.id=a.handover_from WHERE a.status='CALLED' AND a.handover_at IS NOT NULL AND u.role=?
                             AND a.service_code IN ({','.join('?' * len(services))}) ORDER BY a.handover_at""", [role] + list(services))

    def take_over(self, adm_id, user_id=None):
        """Reprise d'un patient réservé : consultation, brouillons et suivi passent au nouveau titulaire (traçé)."""
        role = self._require(user_id, ("medecin", "soins", "labo"))
        with self._tx() as c:
            a = c.execute("""SELECT a.*, u.role AS from_role FROM admissions a LEFT JOIN users u ON u.id=a.handover_from WHERE a.id=?""", (adm_id,)).fetchone()
            if not a or a["handover_at"] is None or a["status"] != "CALLED":
                raise ValueError("Ce patient n'est plus en attente de reprise.")
            if a["from_role"] != role:
                raise PermissionError("Reprise possible uniquement par un professionnel de même rôle.")
            old = a["handover_from"]
            c.execute("""UPDATE admissions SET called_user_id=?, handover_note=NULL, handover_from=NULL, handover_at=NULL WHERE id=?""", (user_id, adm_id))
            c.execute("UPDATE consultations SET doctor_user_id=? WHERE admission_id=? AND ended_at IS NULL", (user_id, adm_id))
            c.execute("DELETE FROM drafts WHERE admission_id=? AND user_id=?", (adm_id, user_id))
            c.execute("UPDATE drafts SET user_id=? WHERE admission_id=? AND user_id=?", (user_id, adm_id, old))
            self._audit(c, adm_id, "TAKE_OVER", {"from": old, "to": user_id}, "")
        return self.get(adm_id)

    # ---------- écran TV : flux d'affichage, voix, annonces, appariement ----------
    def tv_state(self):
        return {"message": self._meta("tv_message"), "paused": self._meta("tv_paused") == "1", "voice": self._meta("tv_voice", "1") == "1"}

    def tv_set(self, message, paused, user_id=None):
        self._require(user_id, ("accueil",))
        with self._tx() as c:
            self._set_meta(c, "tv_message", (message or "").strip()[:200])
            self._set_meta(c, "tv_paused", "1" if paused else "0")
        st = self.tv_state()
        self._tv_notify({"type": "state", **st})
        return st

    def tv_voice(self, enabled, user_id=None):
        """Active / coupe la VOIX des écrans (le bip reste actif)."""
        self._require(user_id, ("accueil", "coord_med", "coord_para"))
        with self._tx() as c:
            self._set_meta(c, "tv_voice", "1" if enabled else "0")
        st = self.tv_state()
        self._tv_notify({"type": "state", **st})
        return st

    def tv_clear(self, user_id=None):
        self._require(user_id, ("accueil",))
        self._tv_notify({"type": "clear"})

    def _may_alert(self, user_id):
        role = self._require(user_id, ("accueil", "coord_med", "coord_para", "medecin"))
        if role == "medecin":
            fn = (self._one("SELECT function FROM users WHERE id=?", (user_id,)) or {}).get("function")
            if fn not in ALERT_FUNCTIONS:
                raise PermissionError("Les alertes sont réservées à l'accueil, aux coordinateurs et au responsable des urgences.")

    def tv_announce(self, text, level="INFO", seconds=60, user_id=None):
        """Bandeau dynamique sur les écrans (INFO / ALERTE / URGENCE), temporisé."""
        self._may_alert(user_id)
        text, level = (text or "").strip()[:200], (level or "INFO").upper()
        if not text or level not in ("INFO", "ALERTE", "URGENCE"):
            raise ValueError("Message vide ou niveau invalide.")
        ann = {"type": "announce", "id": uuid.uuid4().hex[:8], "text": text, "level": level, "seconds": max(5, min(int(seconds), 3600))}
        with self._tx() as c:
            self._audit(c, None, "TV_ANNOUNCE", {"level": level, "user": user_id}, "")
        self._tv_notify(ann)
        return ann["id"]

    def tv_announce_clear(self, ann_id="*", user_id=None):
        self._may_alert(user_id)
        self._tv_notify({"type": "announce_clear", "id": ann_id})

    def tv_pairs(self):
        try:
            d = json.loads(self._meta("tv_pairs") or "{}")
        except ValueError:
            d = {}
        return [{"token": t, "screen": v["screen"], "paired_at": v["at"]} for t, v in d.items()]

    def tv_binding(self, token):
        return next((p["screen"] for p in self.tv_pairs() if p["token"] == token), None)

    def tv_pair(self, code, screen_id, user_id=None):
        """Appariement par code court (TV-4092) : l'accueil saisit le code affiché par la TV et choisit l'écran à lui associer."""
        self._require(user_id, ("accueil",))
        if not any(s["id"] == screen_id for s in self.tv_screens()):
            raise ValueError("Écran inconnu : créez-le d'abord dans Paramètres › Réseau & Écrans TV.")
        hook = getattr(self, "tv_pair_hook", None)
        if hook is None:
            raise ValueError("Appariement impossible : le Hub (serveur des écrans) n'est pas démarré.")
        fails = [t for t in getattr(self, "_pair_fails", []) if t > datetime.now().timestamp() - 60]
        if len(fails) >= 5:
            raise ValueError("Trop de tentatives : patientez une minute.")
        token = hook(code)
        if not token:
            self._pair_fails = fails + [datetime.now().timestamp()]
            raise ValueError("Code inconnu ou expiré : relancez l'affichage du code sur la TV.")
        with self._tx() as c:
            d = {p["token"]: {"screen": p["screen"], "at": p["paired_at"]} for p in self.tv_pairs()}
            d[token] = {"screen": screen_id, "at": now()}
            self._set_meta(c, "tv_pairs", json.dumps(d))
        return True

    def tv_unpair(self, token, user_id=None):
        self._require(user_id, ("accueil",))
        with self._tx() as c:
            d = {p["token"]: {"screen": p["screen"], "at": p["paired_at"]} for p in self.tv_pairs() if p["token"] != token}
            self._set_meta(c, "tv_pairs", json.dumps(d))

    # ---------- écrans TV multiples (dispatching par service) ----------
    def tv_screens(self):
        raw = self._meta("tv_screens")
        try:
            return json.loads(raw) if raw else [{"id": "main", "name": "Salle principale", "services": []}]
        except ValueError:
            return [{"id": "main", "name": "Salle principale", "services": []}]

    def tv_set_screens(self, screens):
        """screens = [{id, name, services:[codes]}] ; services vide = tous les services."""
        clean = []
        for s in screens:
            sid = re.sub(r"[^A-Za-z0-9_-]", "", str(s.get("id", "")))[:20]
            if not sid:
                raise ValueError("Chaque écran TV doit avoir un identifiant (lettres/chiffres).")
            clean.append({"id": sid, "name": str(s.get("name", sid))[:40], "services": [x for x in s.get("services", []) if x in SERVICE_BY_CODE or x == "BIO"]})
        if len({c["id"] for c in clean}) != len(clean):
            raise ValueError("Identifiants d'écrans en double.")
        with self._tx() as c:
            self._set_meta(c, "tv_screens", json.dumps(clean, ensure_ascii=False))
        self._tv_notify({"type": "screens"})
        return clean

    # ---------- rendez-vous du laboratoire ----------
    def _appt_clean(self, d):
        last, first = (d.get("last_name") or "").strip(), (d.get("first_name") or "").strip()
        if not last or not first:
            raise ValueError("Nom et prénom obligatoires.")
        try:
            datetime.strptime(d["date"], "%Y-%m-%d"); datetime.strptime(d["time"], "%H:%M")
        except (KeyError, ValueError):
            raise ValueError("Date (AAAA-MM-JJ) ou heure (HH:MM) invalide.")
        return (last.upper(), first, d.get("birth_year"), (d.get("phone") or "").strip(), (d.get("ident") or "").strip(),
                d["date"], d["time"], (d.get("exam") or "").strip(), (d.get("notes") or "").strip())

    def create_appointment(self, d, user_id=None):
        self._require(user_id, ("labo",))
        v = self._appt_clean(d)
        with self._tx() as c:
            aid = c.execute("""INSERT INTO appointments(last_name,first_name,birth_year,phone,ident,date,time,exam,notes,created_at,created_by)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?)""", v + (now(), user_id)).lastrowid
            self._audit(c, None, "APPT_CREATE", {"id": aid, "user": user_id}, "")
        return self._one("SELECT * FROM appointments WHERE id=?", (aid,))

    def update_appointment(self, appt_id, d, user_id=None):
        self._require(user_id, ("labo",))
        v = self._appt_clean(d)
        with self._tx() as c:
            c.execute("""UPDATE appointments SET last_name=?,first_name=?,birth_year=?,phone=?,ident=?,date=?,time=?,exam=?,notes=?,status=?
                         WHERE id=?""", v + (d.get("status", "PLANNED"), appt_id))
            self._audit(c, None, "APPT_UPDATE", {"id": appt_id, "user": user_id}, "")
        return self._one("SELECT * FROM appointments WHERE id=?", (appt_id,))

    def delete_appointment(self, appt_id, user_id=None):
        self._require(user_id, ("labo",))
        with self._tx() as c:
            c.execute("DELETE FROM appointments WHERE id=?", (appt_id,))
            self._audit(c, None, "APPT_DELETE", {"id": appt_id, "user": user_id}, "")

    def list_appointments(self, date_from, date_to, query="", user_id=None):
        self._require(user_id, ("labo",))
        sql, args = "SELECT * FROM appointments WHERE date BETWEEN ? AND ?", [date_from, date_to]
        if query.strip():
            sql += " AND (last_name LIKE ? OR first_name LIKE ? OR ident LIKE ? OR phone LIKE ?)"; args += [f"%{query.strip()}%"] * 4
        return self._all(sql + " ORDER BY date, time, id", args)

    def appointment_days(self, month, user_id=None):
        """month = 'AAAA-MM' -> {jour: nombre de rendez-vous} (surbrillance du calendrier)."""
        self._require(user_id, ("labo",))
        return {r["date"]: r["n"] for r in self._all(
            "SELECT date, COUNT(*) AS n FROM appointments WHERE date LIKE ? AND status!='CANCELLED' GROUP BY date", (month + "-%",))}

    # ---------- statistiques DSP (agrégats anonymes) ----------
    def stats_report(self, date_from, date_to):
        a, b = date_from + " 00:00:00", date_to + " 23:59:59"
        one = lambda sql, args=(): self._one(sql, args)["n"]
        by = lambda sql: {r["k"]: r["n"] for r in self._all(sql, (a, b))}
        return {
            "date_from": date_from, "date_to": date_to,
            "admissions": one("SELECT COUNT(*) AS n FROM admissions WHERE created_at BETWEEN ? AND ? AND status!='CANCELLED'", (a, b)),
            "by_service": by("SELECT service_code AS k, COUNT(*) AS n FROM admissions WHERE created_at BETWEEN ? AND ? GROUP BY service_code"),
            "by_triage": by("SELECT triage_level AS k, COUNT(*) AS n FROM admissions WHERE created_at BETWEEN ? AND ? AND triage_level IS NOT NULL GROUP BY triage_level"),
            "by_hour": by("SELECT CAST(substr(created_at,12,2) AS INTEGER) AS k, COUNT(*) AS n FROM admissions WHERE created_at BETWEEN ? AND ? GROUP BY k"),
            "avg_wait_min": round((self._one("""SELECT AVG((julianday(called_at)-julianday(created_at))*1440.0) AS n FROM admissions
                                               WHERE called_at IS NOT NULL AND created_at BETWEEN ? AND ?""", (a, b))["n"] or 0), 1),
            "consultations": one("SELECT COUNT(*) AS n FROM consultations WHERE outcome='CLOSED' AND started_at BETWEEN ? AND ?", (a, b)),
            "prescriptions": one("SELECT COUNT(*) AS n FROM prescriptions WHERE created_at BETWEEN ? AND ?", (a, b)),
            "lab_requests": one("SELECT COUNT(*) AS n FROM lab_requests WHERE created_at BETWEEN ? AND ?", (a, b)),
            "radiology": one("SELECT COUNT(*) AS n FROM radiology_requests WHERE created_at BETWEEN ? AND ? AND status IN ('DONE','AWAITING_PRINT')", (a, b)),
            "appointments": one("SELECT COUNT(*) AS n FROM appointments WHERE date BETWEEN ? AND ? AND status!='CANCELLED'", (date_from, date_to)),
        }

    # ---------- synchronisation hors-ligne (outbox) ----------
    def _outbox_add(self, entity, ref, payload):
        with self._tx() as c:
            c.execute("INSERT INTO sync_outbox(entity,ref,payload,created_at) VALUES (?,?,?,?)",
                      (entity, ref, self._enc(json.dumps(payload, ensure_ascii=False)), now()))

    def outbox_pending(self, limit=20):
        return self._all("SELECT * FROM sync_outbox WHERE status='PENDING' AND (next_try IS NULL OR next_try<=?) ORDER BY id LIMIT ?", (now(), limit))

    def outbox_mark(self, oid, ok, error=""):
        with self._tx() as c:
            if ok:
                c.execute("UPDATE sync_outbox SET status='SENT', sent_at=?, last_error=NULL WHERE id=?", (now(), oid))
            else:
                n = c.execute("SELECT attempts FROM sync_outbox WHERE id=?", (oid,)).fetchone()["attempts"] + 1
                nxt = (datetime.now() + timedelta(seconds=min(3600, 30 * 2 ** n))).strftime(FMT)
                c.execute("UPDATE sync_outbox SET attempts=?, last_error=?, next_try=? WHERE id=?", (n, error, nxt, oid))

    # ---------- intégrité & sauvegardes automatiques ----------
    def integrity_ok(self):
        with self.lock:
            return self.conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"

    def auto_backup(self, reason="", keep=14):
        """Sauvegarde quotidienne / de fin de garde dans `backup_dir` (conserve les `keep` plus récentes)."""
        if not self.backup_dir:
            return None
        try:
            dest = self.backup(self.backup_dir)
            files = sorted(f for f in os.listdir(self.backup_dir) if f.startswith("dem_database_") and f.endswith(".db"))
            for old in files[:-keep]:
                os.remove(os.path.join(self.backup_dir, old))
            return dest
        except OSError:
            return None

    def last_backup_age_hours(self):
        if not self.backup_dir or not os.path.isdir(self.backup_dir):
            return 1e9
        files = [os.path.getmtime(os.path.join(self.backup_dir, f)) for f in os.listdir(self.backup_dir) if f.startswith("dem_database_")]
        return (datetime.now().timestamp() - max(files)) / 3600 if files else 1e9

    # ---------- sauvegarde ----------
    def backup(self, folder):
        import os
        os.makedirs(folder, exist_ok=True)
        dest = os.path.join(folder, f"dem_database_{datetime.now():%Y%m%d_%H%M%S}.db")
        dst = sqlite3.connect(dest)
        with self.lock:
            self.conn.backup(dst)
        dst.close()
        return dest
