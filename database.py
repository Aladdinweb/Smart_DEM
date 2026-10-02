"""Couche SQLite : gardes, compteurs, admissions, file d'attente, détection des patients récurrents."""
import json, re, sqlite3, threading, unicodedata
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from config_manager import resource_path
from data_structures import SERVICE_BY_CODE

FMT = "%Y-%m-%d %H:%M:%S"
SCHEMA_VERSION = 1
MIGRATIONS = {}   # {2: "ALTER TABLE ...;"} — une entrée par évolution du schéma (sans jamais supprimer de données)


def now():
    return datetime.now().strftime(FMT)


def norm_name(s):
    """Sans accents, minuscules, tokens triés : 'Ali  BENSALEM' == 'bensalem ali'."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return " ".join(sorted(re.sub(r"[^a-z0-9 ]", " ", s).split()))


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
        if dt > today or y < 1900:
            return None
        return {"birth_date": dt.isoformat(), "birth_year": y}
    return None


def age_from_row(r):
    today = date.today()
    if r.get("birth_date"):
        b = date.fromisoformat(r["birth_date"])
        return today.year - b.year - ((today.month, today.day) < (b.month, b.day))
    return today.year - r["birth_year"]


def birth_text(r):
    if r.get("birth_date"):
        return date.fromisoformat(r["birth_date"]).strftime("%d/%m/%Y")
    return str(age_from_row(r))


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

    def _migrate(self):
        cur = int(self.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])
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

    @contextmanager
    def _tx(self):
        with self.lock:
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

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
        r = self.conn.execute("SELECT * FROM shifts WHERE id=?", (shift_id,)).fetchone()
        return dict(r) if r else None

    def reset_shift(self, station=""):
        """Remet tous les compteurs à zéro : ferme la garde en cours et en ouvre une nouvelle."""
        with self._tx() as c:
            c.execute("UPDATE shifts SET ended_at=? WHERE ended_at IS NULL", (now(),))
            sid = c.execute("INSERT INTO shifts(started_at, started_by) VALUES (?,?)", (now(), station)).lastrowid
            self._audit(c, None, "RESET_COUNTERS", {"new_shift": sid}, station)
            return sid

    def _audit(self, c, adm_id, action, details, station):
        c.execute("INSERT INTO audit_log(admission_id,action,details,station,at) VALUES (?,?,?,?,?)",
                  (adm_id, action, json.dumps(details, ensure_ascii=False, default=str), station, now()))

    # ---------- admissions ----------
    def get(self, adm_id):
        r = self.conn.execute("SELECT * FROM admissions WHERE id=?", (adm_id,)).fetchone()
        return dict(r) if r else None

    def add_admission(self, d, station=""):
        """d = {full_name, parsed, gender, service_code, triage}. Retourne la ligne créée (avec ticket_label)."""
        svc = SERVICE_BY_CODE[d["service_code"]]
        p = d["parsed"]
        with self._tx() as c:
            sid = self._current_shift(c, station)
            c.execute("INSERT OR IGNORE INTO counters(shift_id,service_code,last_number) VALUES (?,?,0)", (sid, svc["code"]))
            c.execute("UPDATE counters SET last_number=last_number+1 WHERE shift_id=? AND service_code=?", (sid, svc["code"]))
            n = c.execute("SELECT last_number FROM counters WHERE shift_id=? AND service_code=?", (sid, svc["code"])).fetchone()[0]
            label = f"{svc['prefix']}-{n:03d}"
            triage = d.get("triage") if svc["triage"] else None
            aid = c.execute(
                """INSERT INTO admissions(shift_id,service_code,ticket_number,ticket_label,full_name,name_norm,
                   birth_date,birth_year,gender,triage_level,created_at,station_name)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sid, svc["code"], n, label, d["full_name"].strip(), norm_name(d["full_name"]),
                 p["birth_date"], p["birth_year"], d["gender"], triage, now(), station)).lastrowid
            self._audit(c, aid, "CREATE", {"ticket": label}, station)
        return self.get(aid)

    def update_admission(self, adm_id, f, station=""):
        """Correction d'erreur : le numéro/label du ticket ne change JAMAIS."""
        svc = SERVICE_BY_CODE[f["service_code"]]
        p = f["parsed"]
        triage = f.get("triage") if svc["triage"] else None
        with self._tx() as c:
            old = self.get(adm_id)
            c.execute("""UPDATE admissions SET full_name=?, name_norm=?, birth_date=?, birth_year=?, gender=?,
                         service_code=?, triage_level=?, modified_at=?, modified_count=modified_count+1 WHERE id=?""",
                      (f["full_name"].strip(), norm_name(f["full_name"]), p["birth_date"], p["birth_year"],
                       f["gender"], svc["code"], triage, now(), adm_id))
            self._audit(c, adm_id, "UPDATE", {"before": {k: old[k] for k in
                        ("full_name", "birth_date", "birth_year", "gender", "service_code", "triage_level")}}, station)
        return self.get(adm_id)

    def history(self, shift_id=None, search=""):
        sql, args = "SELECT * FROM admissions WHERE 1=1", []
        if shift_id:
            sql += " AND shift_id=?"; args.append(shift_id)
        if search:
            sql += " AND (full_name LIKE ? OR ticket_label LIKE ?)"; args += [f"%{search}%"] * 2
        sql += " ORDER BY created_at DESC, id DESC LIMIT 1000"
        return [dict(r) for r in self.conn.execute(sql, args)]

    def stats(self, shift_id):
        c = self.conn
        q = "FROM admissions WHERE shift_id=? AND status!='CANCELLED'"
        total = c.execute(f"SELECT COUNT(*) {q}", (shift_id,)).fetchone()[0]
        tri = {r[0]: r[1] for r in c.execute(f"SELECT triage_level,COUNT(*) {q} AND triage_level IS NOT NULL GROUP BY triage_level", (shift_id,))}
        svc = {r[0]: r[1] for r in c.execute(f"SELECT service_code,COUNT(*) {q} GROUP BY service_code", (shift_id,))}
        return {"total": total, "ROUGE": tri.get("ROUGE", 0), "ORANGE": tri.get("ORANGE", 0),
                "VERT": tri.get("VERT", 0), "by_service": svc}

    # ---------- patients récurrents (information uniquement) ----------
    def find_revisit(self, full_name, gender, parsed, hours, exclude_id=None):
        since = (datetime.now() - timedelta(hours=hours)).strftime(FMT)
        exact = 1 if parsed.get("birth_date") else 0
        sql = """SELECT * FROM admissions WHERE name_norm=:n AND gender=:g AND created_at>=:since
                 AND status!='CANCELLED'
                 AND (birth_year=:y OR (ABS(birth_year-:y)<=1 AND (birth_date IS NULL OR :exact=0)))"""
        args = {"n": norm_name(full_name), "g": gender, "since": since, "y": parsed["birth_year"], "exact": exact}
        if exclude_id:
            sql += " AND id!=:ex"; args["ex"] = exclude_id
        r = self.conn.execute(sql + " ORDER BY created_at DESC LIMIT 1", args).fetchone()
        return dict(r) if r else None

    # ---------- poste médecin ----------
    def queue(self, services):
        if not services:
            return []
        ph = ",".join("?" * len(services))
        rows = self.conn.execute(
            f"""SELECT * FROM admissions WHERE status='WAITING' AND service_code IN ({ph})
                ORDER BY CASE triage_level WHEN 'ROUGE' THEN 0 WHEN 'ORANGE' THEN 1 ELSE 2 END, created_at, id""",
            services).fetchall()
        return [dict(r) for r in rows]

    def current_called(self, station):
        r = self.conn.execute("SELECT * FROM admissions WHERE status='CALLED' AND called_by=? ORDER BY called_at DESC LIMIT 1",
                              (station,)).fetchone()
        return dict(r) if r else None

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

    def _notify(self, row, is_recall, station):
        for cb in list(self.call_listeners):   # ex : le Hub diffuse l'appel à l'écran TV
            try:
                cb(row, is_recall, station)
            except Exception:
                pass

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
