import os, shutil, sqlite3, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import RPC_METHODS, Database, parse_age_or_birth
from github_updater import is_newer, parse_semver


def new_db():
    return Database(os.path.join(tempfile.mkdtemp(), "t.db"))


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = new_db()
        self.p = parse_age_or_birth("35")

    def add(self, last, first, svc, g="H", triage=None, uid=None):
        return self.db.add_admission({"last_name": last, "first_name": first, "parsed": self.p, "gender": g,
                                      "service_code": svc, "triage": triage, "user_id": uid}, "PC")

    def test_tickets_per_service_and_reset(self):
        self.assertEqual(self.add("A", "B", "LAB")["ticket_label"], "LAB-001")
        self.assertEqual(self.add("C", "D", "LAB")["ticket_label"], "LAB-002")
        self.assertEqual(self.add("E", "F", "RAD")["ticket_label"], "RAD-001")
        self.db.reset_shift("PC")
        self.assertEqual(self.add("G", "H", "LAB")["ticket_label"], "LAB-001")

    def test_name_split_and_revisit(self):
        a = self.add("Benali", "Ahmed", "LAB")
        self.assertEqual((a["last_name"], a["first_name"], a["full_name"]), ("BENALI", "Ahmed", "BENALI Ahmed"))
        self.assertIsNotNone(self.db.find_revisit("Ahmed", "BENALI", "H", parse_age_or_birth("36"), 72))   # ordre inversé, âge ±1
        self.assertIsNone(self.db.find_revisit("Benali", "Ahmed", "F", self.p, 72))
        self.add("Benali", "Ahmed", "LAB")   # l'alerte n'est JAMAIS bloquante

    def test_queue_priority_and_recurrent_flag(self):
        self.add("Vert", "Un", "MG", triage="VERT"); self.add("Rouge", "Un", "MG", triage="ROUGE")
        self.add("Vert", "Un", "MG", triage="VERT")           # revient : doit être signalé récurrent
        q = self.db.queue(["MG"], 72)
        self.assertEqual([x["ticket_label"] for x in q], ["MG-002", "MG-001", "MG-003"])
        self.assertEqual([x["recurrent"] for x in q], [0, 0, 1])

    def test_call_listener_and_edit_keeps_ticket(self):
        seen = []
        self.db.call_listeners.append(lambda row, rc, st: seen.append((row["ticket_label"], rc)))
        a = self.add("X", "Y", "MG", triage="ROUGE")
        self.assertEqual(self.db.call_next(["MG"], "DOC")["ticket_label"], "MG-001")
        self.assertEqual(seen, [("MG-001", False)])
        u = self.db.update_admission(a["id"], {"last_name": "Z", "first_name": "W", "parsed": self.p, "gender": "H",
                                               "service_code": "RAD"}, "PC")
        self.assertEqual((u["ticket_label"], u["service_code"], u["modified_count"]), ("MG-001", "RAD", 1))


class UserTests(unittest.TestCase):
    def test_pin_and_lockout(self):
        db = new_db()
        uid = db.create_user("dupont", "Marie", "medecin", "Généraliste", "1234")
        self.assertTrue(db.verify_pin(uid, "1234")["ok"])
        self.assertEqual(db.verify_pin(uid, "1234")["user"]["last_name"], "DUPONT")
        for _ in range(5):
            r = db.verify_pin(uid, "0000")
        self.assertFalse(r["ok"]); self.assertIn("verrouillé", r["error"])
        self.assertFalse(db.verify_pin(uid, "1234")["ok"])      # verrouillé même avec le bon PIN
        with self.assertRaises(ValueError): db.create_user("A", "B", "medecin", "", "12")
        with self.assertRaises(ValueError): db.create_user("A", "B", "chef", "", "1234")
        self.assertNotIn("pin_hash", db.list_users()[0])
        self.assertEqual(db.list_users(roles=["radio"]), [])


class ClinicalFlowTests(unittest.TestCase):
    def setUp(self):
        self.db = new_db()
        self.doc = self.db.create_user("Martin", "Paul", "medecin", "Généraliste", "1111")
        self.tech = self.db.create_user("Radi", "Sam", "radio", "", "2222")
        self.pharm = self.db.create_user("Pharma", "Lia", "pharmacie", "", "3333")
        p = parse_age_or_birth("40")
        self.adm = self.db.add_admission({"last_name": "Said", "first_name": "Omar", "parsed": p, "gender": "H",
                                          "service_code": "MG", "triage": "ORANGE"}, "ACC")
        self.db.call_next(["MG"], "DOC1")
        self.cons = self.db.start_consultation(self.adm["id"], self.doc, "DOC1")

    def test_consultation_idempotent(self):
        self.assertEqual(self.db.start_consultation(self.adm["id"], self.doc, "DOC1")["id"], self.cons["id"])

    def test_prescription_qr_authenticity_and_pharmacy(self):
        items = [{"drug": "Paracétamol 500 mg cp", "dosage": "1 cp x 3/j", "duration": "5 jours"},
                 {"drug": "Médicament libre", "dosage": "", "duration": ""}, {"drug": "  "}]
        rx = self.db.create_prescription(self.cons["id"], items, "repos", self.doc)
        self.assertEqual(len(rx["items"]), 2)
        self.assertRegex(rx["qr_text"], r"^SDEM1[0-9a-f]{48}$")
        self.assertIn("Médicament libre", self.db.list_drug_names())          # le dictionnaire s'enrichit
        self.assertEqual(self.db.pharmacy_queue(), [])
        self.db.send_to_pharmacy(rx["uuid"], self.doc)
        q = self.db.pharmacy_queue(); self.assertEqual(len(q), 1); self.assertEqual(q[0]["patient"]["nom"], "SAID")
        ok = self.db.pharmacy_lookup(rx["qr_text"]); self.assertTrue(ok["authentic"])
        forged = self.db.pharmacy_lookup("SDEM1" + rx["uuid"] + "0" * 16); self.assertFalse(forged["authentic"])
        unknown = self.db.pharmacy_lookup("SDEM1" + "a" * 32 + "b" * 16); self.assertFalse(unknown["found"])
        manual = self.db.pharmacy_lookup(rx["uuid"][:10]); self.assertIsNone(manual["authentic"])
        self.assertTrue(self.db.pharmacy_dispense(rx["uuid"], self.pharm)["ok"])
        self.assertFalse(self.db.pharmacy_dispense(rx["uuid"], self.pharm)["ok"])   # déjà délivrée
        self.assertEqual(self.db.pharmacy_queue(), [])
        with self.assertRaises(ValueError): self.db.create_prescription(self.cons["id"], [{"drug": ""}], "", self.doc)

    def test_tampered_prescription_detected(self):
        rx = self.db.create_prescription(self.cons["id"], [{"drug": "A", "dosage": "1", "duration": "1"}], "", self.doc)
        self.db.conn.execute("UPDATE prescriptions SET canonical=replace(canonical,'\"A\"','\"B\"') WHERE uuid=?", (rx["uuid"],))
        self.assertFalse(self.db.pharmacy_lookup(rx["qr_text"])["authentic"])

    def test_radiology_bridge(self):
        r1 = self.db.create_radio_request(self.cons["id"], "Radio X", "Thorax", "Droit", "toux", False, self.doc, "DOC1")
        r2 = self.db.create_radio_request(self.cons["id"], "Scanner", "Crâne", "Non applicable", "chute", True, self.doc, "DOC1")
        direct = self.db.add_admission({"last_name": "Direct", "first_name": "Ali", "parsed": parse_age_or_birth("20"),
                                        "gender": "H", "service_code": "RAD"}, "ACC")
        self.assertEqual([r1["ticket_label"], r2["ticket_label"], direct["ticket_label"]], ["RAD-001", "RAD-002", "RAD-003"])
        order = [r["ticket_label"] for r in self.db.radio_queue()]
        self.assertEqual(order, ["RAD-002", "RAD-001", "RAD-003"])       # l'urgent passe en premier
        seen = []; self.db.call_listeners.append(lambda row, rc, st: seen.append(row["ticket_label"]))
        c = self.db.radio_call_next("RADIO1", self.tech); self.assertEqual(c["ticket_label"], "RAD-002")
        self.assertEqual(seen, ["RAD-002"])                                # l'écran TV reçoit l'appel
        v = self.db.radio_validate(c["id"], "AWAITING_PRINT", "cliché à tirer", self.tech)
        self.assertEqual(v["status"], "AWAITING_PRINT")
        self.assertEqual(len(self.db.radio_awaiting()), 1)
        mine = {r["ticket_label"]: r["status"] for r in self.db.radio_requests_for_doctor(self.doc)}
        self.assertEqual(mine["RAD-002"], "AWAITING_PRINT")                # statut remonté vers le médecin
        c2 = self.db.radio_call_next("RADIO1", self.tech)                  # prochain = RAD-001
        c3 = self.db.radio_call_next("RADIO1", self.tech)                  # non validé -> reporté puis rappelé
        self.assertEqual((c2["ticket_label"], c3["ticket_label"]), ("RAD-001", "RAD-003"))
        self.db.radio_validate(c3["id"], "DONE", "", self.tech)
        self.assertEqual(self.db.get(direct["id"])["status"], "DONE")      # inscription directe : dossier clos

    def test_lab_and_close_dossier(self):
        lab = self.db.create_lab_request(self.cons["id"], ["NFS", "CRP"], "fièvre", self.doc)
        self.assertEqual(lab["items"], ["NFS", "CRP"])
        with self.assertRaises(ValueError): self.db.create_lab_request(self.cons["id"], [], "", self.doc)
        self.db.create_prescription(self.cons["id"], [{"drug": "X", "dosage": "1", "duration": "1"}], "", self.doc)
        d = self.db.close_consultation(self.cons["id"], "RAS", "Angine")
        self.assertEqual((d["consultation"]["diagnosis"], d["patient"]["status"]), ("Angine", "DONE"))
        self.assertEqual((len(d["prescriptions"]), len(d["lab_requests"])), (1, 1))
        self.assertEqual(d["doctor"]["last_name"], "MARTIN")


class MigrationTests(unittest.TestCase):
    def test_v1_database_is_migrated_without_data_loss(self):
        d = tempfile.mkdtemp(); path = os.path.join(d, "dem_database.db")
        con = sqlite3.connect(path)
        with open(os.path.join(os.path.dirname(__file__), "fixtures", "schema_v1.sql"), encoding="utf-8") as f:
            con.executescript(f.read())
        con.execute("INSERT INTO shifts(started_at) VALUES ('2026-10-01 08:00:00')")
        con.execute("INSERT INTO counters(shift_id,service_code,last_number) VALUES (1,'LAB',1)")   # comme une vraie base v1
        con.execute("""INSERT INTO admissions(shift_id,service_code,ticket_number,ticket_label,full_name,name_norm,birth_year,gender,created_at)
                       VALUES (1,'LAB',1,'LAB-001','Benali Ahmed','ahmed benali',1990,'H','2026-10-01 08:05:00')""")
        con.commit(); con.close()
        db = Database(path)
        self.assertEqual(db._one("SELECT value FROM meta WHERE key='schema_version'")["value"], "2")
        a = db.get(1)
        self.assertEqual((a["ticket_label"], a["full_name"], a["last_name"], a["first_name"]), ("LAB-001", "Benali Ahmed", "Benali Ahmed", ""))
        self.assertTrue(os.path.isdir(os.path.join(d, "backups")))        # sauvegarde automatique avant migration
        db.add_admission({"last_name": "Neuf", "first_name": "Patient", "parsed": parse_age_or_birth("30"), "gender": "F", "service_code": "LAB"}, "PC")
        Database(path)                                                    # réouverture : pas de seconde migration


class SemVerAndRpcTests(unittest.TestCase):
    def test_semver(self):
        self.assertTrue(is_newer("v1.1.0", "1.0.0")); self.assertTrue(is_newer("v1.10.0", "1.9.9"))
        self.assertFalse(is_newer("v1.0.0", "1.0.0")); self.assertFalse(is_newer("v2.0.0-rc.1", "2.0.0"))
        self.assertFalse(is_newer("n'importe quoi", "1.0.0")); self.assertIsNone(parse_semver("1.0"))

    def test_every_rpc_method_exists(self):
        for m in RPC_METHODS:
            self.assertTrue(callable(getattr(Database, m, None)), m)


try:
    import flask, flask_sock  # noqa
    HAVE_FLASK = True
except ImportError:
    HAVE_FLASK = False


@unittest.skipUnless(HAVE_FLASK, "flask / flask-sock non installés")
class HubTests(unittest.TestCase):
    def test_rpc_token_and_tv_event(self):
        from hub_server import Hub

        class Cfg:
            def get(self, k, d=None):
                return {"lan_token": "secret", "parent": "EPSP X", "structure": "POLY Y"}.get(k, d)

        db = new_db(); hub = Hub(db, Cfg()); c = hub.app.test_client()
        body = {"m": "current_shift", "a": ["PC"], "k": {}}
        self.assertEqual(c.post("/rpc", json=body).status_code, 403)
        self.assertEqual(c.post("/rpc", json=body, headers={"X-DEM-Token": "secret"}).status_code, 200)
        self.assertEqual(c.post("/rpc", json={"m": "backup"}, headers={"X-DEM-Token": "secret"}).status_code, 400)
        self.assertEqual(c.get("/api/ping").get_json()["name"], "EPSP X — POLY Y")
        hub.test_call(); self.assertEqual(hub.recent[0]["ticket"], "TEST-000")
        self.assertIn("ws/tv", c.get("/tv").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
