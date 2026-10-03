"""Couche SQLite : utilisateurs (PIN), gardes, admissions, consultations, ordonnances sécurisées, radiologie,
analyses, pharmacie. Toutes les méthodes publiques de RPC_METHODS sont aussi appelables à distance via le Hub."""
import hashlib, hmac, json, re, secrets, sqlite3, threading, unicodedata, uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from config_manager import resource_path
from data_structures import SERVICE_BY_CODE
from medical_data import DRUGS_SEED

FMT = "%Y-%m-%d %H:%M:%S"
SCHEMA_VERSION = 2
ROLES = ("accueil", "medecin", "radio", "pharmacie")
MIGRATIONS = {
    2: """ALTER TABLE admissions ADD COLUMN last_name TEXT;
          ALTER TABLE admissions ADD COLUMN first_name TEXT;
          ALTER TABLE admissions ADD COLUMN created_by INTEGER;
          UPDATE admissions SET last_name = full_name, first_name = '' WHERE last_name IS NULL;""",
}


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
    u.last_name AS doc_last, u.first_name AS doc_first
    FROM radiology_requests r LEFT JOIN admissions a ON a.id=r.admission_id
    LEFT JOIN users u ON u.id=r.doctor_user_id"""

RPC_METHODS = (
    "current_shift", "shift_info", "reset_shift", "get", "add_admission", "update_admission", "history", "stats",
    "find_revisit", "queue", "current_called", "call_next", "recall", "finish",
    "count_users", "list_users", "create_user", "update_user", "reset_user_pin", "change_own_pin", "verify_pin",
    "get_user", "set_signature", "list_drug_names", "add_drug",
    "start_consultation", "close_consultation", "consultation_dossier",
    "create_prescription", "get_prescription", "send_to_pharmacy", "pharmacy_queue", "pharmacy_lookup", "pharmacy_dispense",
    "create_radio_request", "radio_queue", "radio_awaiting", "radio_call_next", "radio_recall", "radio_validate",
    "radio_requests_for_doctor", "radio_for_consultation", "create_lab_request",
)


class Database:
    def __init__(self, path):
        self.path = path
        self.call_listeners = []
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        with open(resource_path("schema.sql"), encoding="utf-8") as f:
            self.conn.executescript(f.read())
        self.conn.commit()
        self._migrate()
        self._ensure_key()
        self._seed_drugs()

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

    def _one(self, sql, args=()):
        with self.lock:
            r = self.conn.execute(sql, args).fetchone()
        return dict(r) if r else None

    def _all(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args)]

    def _migrate(self):
        cur = int(self._one("SELECT value FROM meta WHERE key='schema_version'")["value"])
        if cur > SCHEMA_VERSION:
            raise RuntimeError("Base de données plus récente que le programme : mettez à jour Smart DEM.")
        if cur == SCHEMA_VERSION:
            return
        import os
        self.backup(os.path.join(os.path.dirname(self.path), "backups"))   # sécurité avant migration
        for v in range(cur + 1, SCHEMA_VERSION + 1):
            self.conn.executescript(MIGRATIONS[v])
            self.conn.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(v),))
        self.conn.commit()

    def _ensure_key(self):
        with self._tx() as c:
            if not c.execute("SELECT 1 FROM meta WHERE key='signing_key'").fetchone():
                c.execute("INSERT INTO meta(key,value) VALUES ('signing_key',?)", (secrets.token_hex(32),))

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

    def reset_shift(self, station=""):
        """Remet tous les compteurs à zéro : ferme la garde en cours et en ouvre une nouvelle."""
        with self._tx() as c:
            c.execute("UPDATE shifts SET ended_at=? WHERE ended_at IS NULL", (now(),))
            sid = c.execute("INSERT INTO shifts(started_at, started_by) VALUES (?,?)", (now(), station)).lastrowid
            self._audit(c, None, "RESET_COUNTERS", {"new_shift": sid}, station)
            return sid

    # ---------- utilisateurs ----------
    @staticmethod
    def _public_user(u):
        return {"id": u["id"], "last_name": u["last_name"], "first_name": u["first_name"], "role": u["role"],
                "specialty": u["specialty"] or "", "active": u["active"], "has_signature": bool(u["signature_b64"])}

    def count_users(self):
        return self._one("SELECT COUNT(*) AS n FROM users WHERE active=1")["n"]

    def list_users(self, roles=None, active_only=True):
        sql, args = "SELECT * FROM users WHERE 1=1", []
        if active_only:
            sql += " AND active=1"
        if roles:
            sql += f" AND role IN ({','.join('?' * len(roles))})"; args += list(roles)
        return [self._public_user(u) for u in self._all(sql + " ORDER BY last_name, first_name", args)]

    def create_user(self, last_name, first_name, role, specialty, pin):
        if role not in ROLES:
            raise ValueError("Rôle invalide.")
        if not (last_name or "").strip() or not (first_name or "").strip():
            raise ValueError("Nom et prénom obligatoires.")
        if not re.fullmatch(r"\d{4}", pin or ""):
            raise ValueError("Le code PIN doit contenir exactement 4 chiffres.")
        salt = secrets.token_hex(16)
        with self._tx() as c:
            return c.execute("""INSERT INTO users(last_name,first_name,role,specialty,pin_salt,pin_hash,created_at)
                                VALUES (?,?,?,?,?,?,?)""", (last_name.strip().upper(), first_name.strip(), role,
                                                            (specialty or "").strip(), salt, _hash_pin(pin, salt), now())).lastrowid

    def update_user(self, user_id, fields):
        allowed = {k: v for k, v in fields.items() if k in ("last_name", "first_name", "role", "specialty", "active")}
        if "role" in allowed and allowed["role"] not in ROLES:
            raise ValueError("Rôle invalide.")
        if "last_name" in allowed:
            allowed["last_name"] = allowed["last_name"].strip().upper()
        if not allowed:
            return
        with self._tx() as c:
            c.execute(f"UPDATE users SET {','.join(k + '=?' for k in allowed)} WHERE id=?", list(allowed.values()) + [user_id])

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
                return {"ok": True, "user": self._public_user(u)}
            n = u["failed_count"] + 1
            lock = (datetime.now() + timedelta(seconds=60)).strftime(FMT) if n >= 5 else None
            c.execute("UPDATE users SET failed_count=?, locked_until=? WHERE id=?", (0 if lock else n, lock, user_id))
            return {"ok": False, "error": "Compte verrouillé 60 secondes." if lock else f"Code PIN incorrect ({n}/5)."}

    def get_user(self, user_id):
        u = self._one("SELECT * FROM users WHERE id=?", (user_id,))
        if not u:
            return None
        d = self._public_user(u)
        d["signature_b64"] = u["signature_b64"]
        return d

    def set_signature(self, user_id, b64):
        if b64 and len(b64) > 700_000:
            raise ValueError("Image de griffe trop volumineuse.")
        with self._tx() as c:
            c.execute("UPDATE users SET signature_b64=? WHERE id=?", (b64 or None, user_id))

    # ---------- médicaments ----------
    def list_drug_names(self):
        return [r["name"] for r in self._all("SELECT name FROM drugs ORDER BY uses DESC, name")]

    def add_drug(self, name):
        name = (name or "").strip()
        if name:
            with self._tx() as c:
                c.execute("INSERT OR IGNORE INTO drugs(name,uses) VALUES (?,0)", (name,))
                c.execute("UPDATE drugs SET uses=uses+1 WHERE name=?", (name,))

    # ---------- admissions ----------
    def get(self, adm_id):
        return self._one("SELECT * FROM admissions WHERE id=?", (adm_id,))

    def add_admission(self, d, station=""):
        """d = {last_name, first_name, parsed, gender, service_code, triage?, user_id?}."""
        svc = SERVICE_BY_CODE[d["service_code"]]
        p, last, first = d["parsed"], d["last_name"].strip(), d["first_name"].strip()
        full = f"{last.upper()} {first}".strip()
        with self._tx() as c:
            sid = self._current_shift(c, station)
            n, label = self._next_ticket(c, sid, svc)
            triage = d.get("triage") if svc["triage"] else None
            aid = c.execute(
                """INSERT INTO admissions(shift_id,service_code,ticket_number,ticket_label,full_name,name_norm,
                   birth_date,birth_year,gender,triage_level,created_at,station_name,last_name,first_name,created_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sid, svc["code"], n, label, full, norm_name(last, first), p["birth_date"], p["birth_year"],
                 d["gender"], triage, now(), station, last.upper(), first, d.get("user_id"))).lastrowid
            if svc["code"] == "RAD":   # inscription directe en radiologie : apparaît dans la file du manipulateur
                c.execute("""INSERT INTO radiology_requests(uuid,source,admission_id,ticket_label,status,created_at,queue_ts)
                             VALUES (?,?,?,?,?,?,?)""", (uuid.uuid4().hex, "RECEPTION", aid, label, "PENDING", now(), now_us()))
            self._audit(c, aid, "CREATE", {"ticket": label}, station)
        return self.get(aid)

    def update_admission(self, adm_id, f, station=""):
        """Correction d'erreur : le numéro/label du ticket ne change JAMAIS."""
        svc = SERVICE_BY_CODE[f["service_code"]]
        p, last, first = f["parsed"], f["last_name"].strip(), f["first_name"].strip()
        triage = f.get("triage") if svc["triage"] else None
        with self._tx() as c:
            old = self.get(adm_id)
            c.execute("""UPDATE admissions SET full_name=?, name_norm=?, last_name=?, first_name=?, birth_date=?, birth_year=?,
                         gender=?, service_code=?, triage_level=?, modified_at=?, modified_count=modified_count+1 WHERE id=?""",
                      (f"{last.upper()} {first}".strip(), norm_name(last, first), last.upper(), first, p["birth_date"],
                       p["birth_year"], f["gender"], svc["code"], triage, now(), adm_id))
            self._audit(c, adm_id, "UPDATE", {"before": {k: old[k] for k in
                        ("full_name", "birth_date", "birth_year", "gender", "service_code", "triage_level")}}, station)
        return self.get(adm_id)

    def history(self, shift_id=None, search=""):
        sql, args = "SELECT * FROM admissions WHERE 1=1", []
        if shift_id:
            sql += " AND shift_id=?"; args.append(shift_id)
        if search:
            sql += " AND (full_name LIKE ? OR ticket_label LIKE ?)"; args += [f"%{search}%"] * 2
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

    # ---------- poste médecin ----------
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

    def current_called(self, station):
        return self._one("SELECT * FROM admissions WHERE status='CALLED' AND called_by=? ORDER BY called_at DESC LIMIT 1", (station,))

    def call_next(self, services, station):
        """Appelle le patient prioritaire ; le précédent patient de ce poste passe en 'terminé'."""
        q = self.queue(services)
        if not q:
            return None
        nxt = q[0]
        with self._tx() as c:
            c.execute("UPDATE admissions SET status='DONE', finished_at=? WHERE status='CALLED' AND called_by=?", (now(), station))
            c.execute("UPDATE admissions SET status='CALLED', called_at=?, called_by=? WHERE id=?", (now(), station, nxt["id"]))
            c.execute("INSERT INTO calls(admission_id,called_at,station) VALUES (?,?,?)", (nxt["id"], now(), station))
        row = self.get(nxt["id"])
        self._notify(row, False, station)
        return row

    def recall(self, adm_id, station):
        with self._tx() as c:
            c.execute("INSERT INTO calls(admission_id,called_at,station,is_recall) VALUES (?,?,?,1)", (adm_id, now(), station))
        row = self.get(adm_id)
        self._notify(row, True, station)
        return row

    def finish(self, adm_id):
        with self._tx() as c:
            c.execute("UPDATE admissions SET status='DONE', finished_at=? WHERE id=?", (now(), adm_id))

    # ---------- consultation ----------
    def start_consultation(self, admission_id, user_id, station=""):
        with self._tx() as c:
            r = c.execute("SELECT * FROM consultations WHERE admission_id=? AND ended_at IS NULL", (admission_id,)).fetchone()
            if not r:
                cid = c.execute("INSERT INTO consultations(admission_id,doctor_user_id,station,started_at) VALUES (?,?,?,?)",
                                (admission_id, user_id, station, now())).lastrowid
                r = c.execute("SELECT * FROM consultations WHERE id=?", (cid,)).fetchone()
            return dict(r)

    def close_consultation(self, cid, notes="", diagnosis=""):
        with self._tx() as c:
            cons = c.execute("SELECT * FROM consultations WHERE id=?", (cid,)).fetchone()
            c.execute("UPDATE consultations SET ended_at=?, notes=?, diagnosis=? WHERE id=?", (now(), notes, diagnosis, cid))
            c.execute("UPDATE admissions SET status='DONE', finished_at=COALESCE(finished_at,?) WHERE id=?", (now(), cons["admission_id"]))
        return self.consultation_dossier(cid)

    def consultation_dossier(self, cid):
        cons = self._one("SELECT * FROM consultations WHERE id=?", (cid,))
        doc = self._one("SELECT * FROM users WHERE id=?", (cons["doctor_user_id"],))
        rx = [self._rx(r["uuid"]) for r in self._all("SELECT uuid FROM prescriptions WHERE consultation_id=?", (cid,))]
        labs = self._all("SELECT * FROM lab_requests WHERE consultation_id=?", (cid,))
        for l in labs:
            l["items"] = json.loads(l.pop("items_json"))
        return {"consultation": cons, "patient": self.get(cons["admission_id"]),
                "doctor": self._public_user(doc) if doc else None, "prescriptions": rx,
                "radiology": self._all(_RADIO_SELECT + " WHERE r.consultation_id=? ORDER BY r.id", (cid,)), "lab_requests": labs}

    # ---------- ordonnance numérique ----------
    def _rx(self, uid):
        r = self._one("SELECT * FROM prescriptions WHERE uuid=?", (uid,))
        if not r:
            return None
        r["items"] = json.loads(r["items_json"])
        r["qr_text"] = f"SDEM1{r['uuid']}{r['sig']}"
        r["patient"] = self.get(r["admission_id"])
        u = self._one("SELECT * FROM users WHERE id=?", (r["doctor_user_id"],))
        r["doctor"] = self._public_user(u) if u else None
        return r

    def create_prescription(self, consultation_id, items, notes="", user_id=None):
        items = [{"drug": (i.get("drug") or "").strip(), "dosage": (i.get("dosage") or "").strip(),
                  "duration": (i.get("duration") or "").strip()} for i in items if (i.get("drug") or "").strip()]
        if not items:
            raise ValueError("L'ordonnance est vide.")
        cons = self._one("SELECT * FROM consultations WHERE id=?", (consultation_id,))
        adm = self.get(cons["admission_id"])
        uid, created = uuid.uuid4().hex, now()
        canonical = json.dumps({"uuid": uid, "patient": {"nom": adm["last_name"], "prenom": adm["first_name"],
                                "annee": adm["birth_year"], "genre": adm["gender"]}, "doctor": user_id,
                                "date": created, "items": items, "notes": notes or ""}, sort_keys=True, ensure_ascii=False)
        chash = hashlib.sha256(canonical.encode()).hexdigest()
        with self._tx() as c:
            c.execute("""INSERT INTO prescriptions(uuid,consultation_id,admission_id,doctor_user_id,items_json,notes,
                         canonical,content_hash,sig,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                      (uid, consultation_id, adm["id"], user_id, json.dumps(items, ensure_ascii=False), notes or "",
                       canonical, chash, self._sign(uid + chash)[:16], created))
        for i in items:
            self.add_drug(i["drug"])
        return self._rx(uid)

    def get_prescription(self, uid):
        return self._rx(uid)

    def send_to_pharmacy(self, uid, user_id=None):
        rx = self._rx(uid)
        if rx["status"] != "CREATED":
            return rx
        light = {"uuid": uid, "qr_text": rx["qr_text"], "date": rx["created_at"],
                 "patient": {"nom": rx["patient"]["last_name"], "prenom": rx["patient"]["first_name"],
                             "age": age_from_row(rx["patient"]), "genre": rx["patient"]["gender"]},
                 "doctor": f"{rx['doctor']['last_name']} {rx['doctor']['first_name']}" if rx["doctor"] else "",
                 "items": rx["items"], "notes": rx["notes"]}
        with self._tx() as c:
            c.execute("UPDATE prescriptions SET status='SENT', sent_at=? WHERE uuid=?", (now(), uid))
            c.execute("INSERT INTO transit_queue(channel,ref_uuid,payload,created_at) VALUES ('pharmacie',?,?,?)",
                      (uid, json.dumps(light, ensure_ascii=False), now()))
        return self._rx(uid)

    def pharmacy_queue(self):
        out = []
        for r in self._all("SELECT * FROM transit_queue WHERE channel='pharmacie' AND status='PENDING' ORDER BY id"):
            p = json.loads(r["payload"]); p["transit_id"] = r["id"]; out.append(p)
        return out

    def pharmacy_lookup(self, text):
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
        if re.fullmatch(r"[0-9a-fA-F]{8,32}", t):
            rows = self._all("SELECT uuid FROM prescriptions WHERE uuid LIKE ?", (t.lower() + "%",))
            if len(rows) == 1:
                return {"found": True, "authentic": None, "rx": self._rx(rows[0]["uuid"]),
                        "reason": "Saisie manuelle : authenticité non vérifiable, scannez le QR Code."}
        return {"found": False, "authentic": False, "reason": "Code illisible ou ordonnance introuvable."}

    def pharmacy_dispense(self, uid, user_id=None):
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

    def create_radio_request(self, consultation_id, exam_type, region, side, clinical_info, urgent, user_id, station=""):
        with self._tx() as c:
            cons = c.execute("SELECT * FROM consultations WHERE id=?", (consultation_id,)).fetchone()
            sid = self._current_shift(c, station)
            _, label = self._next_ticket(c, sid, SERVICE_BY_CODE["RAD"])
            rid = c.execute("""INSERT INTO radiology_requests(uuid,source,consultation_id,admission_id,doctor_user_id,ticket_label,
                               exam_type,region,side,clinical_info,urgent,status,created_at,queue_ts)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (uuid.uuid4().hex, "MEDECIN", consultation_id, cons["admission_id"], user_id, label, exam_type,
                             region, side, clinical_info, 1 if urgent else 0, "PENDING", now(), now_us())).lastrowid
        return self._radio_row(rid)

    def radio_queue(self):
        return self._all(_RADIO_SELECT + " WHERE r.status IN ('PENDING','CALLED') ORDER BY r.urgent DESC, r.queue_ts, r.id")

    def radio_awaiting(self):
        return self._all(_RADIO_SELECT + " WHERE r.status='AWAITING_PRINT' ORDER BY r.done_at")

    def radio_call_next(self, station, user_id=None):
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
        self._notify({"ticket_label": row["ticket_label"], "service_code": "RAD"}, False, station)
        return row

    def radio_recall(self, request_id, station):
        row = self._radio_row(request_id)
        self._notify({"ticket_label": row["ticket_label"], "service_code": "RAD"}, True, station)
        return row

    def radio_validate(self, request_id, status, note="", user_id=None):
        if status not in ("DONE", "AWAITING_PRINT"):
            raise ValueError("Statut invalide.")
        with self._tx() as c:
            r = c.execute("SELECT * FROM radiology_requests WHERE id=?", (request_id,)).fetchone()
            c.execute("UPDATE radiology_requests SET status=?, done_at=COALESCE(done_at,?), tech_user_id=?, result_note=? WHERE id=?",
                      (status, now(), user_id, note or r["result_note"], request_id))
            if r["source"] == "RECEPTION" and r["admission_id"]:
                c.execute("UPDATE admissions SET status='DONE', finished_at=COALESCE(finished_at,?) WHERE id=?", (now(), r["admission_id"]))
        return self._radio_row(request_id)

    def radio_requests_for_doctor(self, user_id, hours=24):
        since = (datetime.now() - timedelta(hours=hours)).strftime(FMT)
        return self._all(_RADIO_SELECT + " WHERE r.doctor_user_id=? AND r.created_at>=? ORDER BY r.id DESC", (user_id, since))

    def radio_for_consultation(self, cid):
        return self._all(_RADIO_SELECT + " WHERE r.consultation_id=? ORDER BY r.id", (cid,))

    # ---------- demandes d'analyses ----------
    def create_lab_request(self, consultation_id, items, clinical_info="", user_id=None):
        items = [i.strip() for i in items if i and i.strip()]
        if not items:
            raise ValueError("Sélectionnez au moins une analyse.")
        cons = self._one("SELECT * FROM consultations WHERE id=?", (consultation_id,))
        uid = uuid.uuid4().hex
        with self._tx() as c:
            c.execute("""INSERT INTO lab_requests(uuid,consultation_id,admission_id,doctor_user_id,items_json,clinical_info,created_at)
                         VALUES (?,?,?,?,?,?,?)""", (uid, consultation_id, cons["admission_id"], user_id,
                                                      json.dumps(items, ensure_ascii=False), clinical_info or "", now()))
        r = self._one("SELECT * FROM lab_requests WHERE uuid=?", (uid,))
        r["items"] = json.loads(r.pop("items_json"))
        return r

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
