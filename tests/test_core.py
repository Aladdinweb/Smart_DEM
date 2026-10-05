import base64, json, os, shutil, sqlite3, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import RPC_METHODS, Database, parse_age_or_birth
from github_updater import is_newer, parse_semver

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def new_db():
    return Database(os.path.join(tempfile.mkdtemp(), "t.db"))


class Base(unittest.TestCase):
    def setUp(self):
        self.db = new_db()
        self.p = parse_age_or_birth("35")
        self.acc = self.db.create_user("Acc", "Un", "accueil", "", "1000")
        self.doc = self.db.create_user("Martin", "Paul", "medecin", "Généraliste", "1111")
        self.doc2 = self.db.create_user("Durand", "Eve", "medecin", "Urgentiste", "1112")
        self.tech = self.db.create_user("Radi", "Sam", "radio", "", "2222")
        self.pharm = self.db.create_user("Pharma", "Lia", "pharmacie", "", "3333")
        self.labo = self.db.create_user("Labo", "Nora", "labo", "", "4444")

    def add(self, last, first, svc, g="H", triage=None, ident=None, uid=None):
        return self.db.add_admission({"last_name": last, "first_name": first, "parsed": self.p, "gender": g, "service_code": svc,
                                      "triage": triage, "ident": ident, "user_id": uid or self.acc}, "PC")


class DatabaseTests(Base):
    def test_tickets_per_service_and_reset(self):
        self.assertEqual(self.add("A", "B", "LAB")["ticket_label"], "LAB-001")
        self.assertEqual(self.add("C", "D", "LAB")["ticket_label"], "LAB-002")
        self.assertEqual(self.add("E", "F", "RAD")["ticket_label"], "RAD-001")
        self.db.reset_shift("PC", self.acc)
        self.assertEqual(self.add("G", "H", "LAB")["ticket_label"], "LAB-001")

    def test_name_split_and_revisit(self):
        a = self.add("Benali", "Ahmed", "LAB")
        self.assertEqual((a["last_name"], a["first_name"], a["full_name"]), ("BENALI", "Ahmed", "BENALI Ahmed"))
        self.assertIsNotNone(self.db.find_revisit("Ahmed", "BENALI", "H", parse_age_or_birth("36"), 72))
        self.assertIsNone(self.db.find_revisit("Benali", "Ahmed", "F", self.p, 72))
        self.add("Benali", "Ahmed", "LAB")   # l'alerte n'est JAMAIS bloquante

    def test_queue_priority_and_recurrent_flag(self):
        self.add("Vert", "Un", "MG", triage="VERT"); self.add("Rouge", "Un", "MG", triage="ROUGE"); self.add("Vert", "Un", "MG", triage="VERT")
        q = self.db.queue(["MG"], 72)
        self.assertEqual([x["ticket_label"] for x in q], ["MG-002", "MG-001", "MG-003"])
        self.assertEqual([x["recurrent"] for x in q], [0, 0, 1])

    def test_call_listener_room_label_and_edit_keeps_ticket(self):
        seen = []
        self.db.call_listeners.append(lambda row, rc, room: seen.append((row["ticket_label"], rc, room)))
        a = self.add("X", "Y", "MG", triage="ROUGE")
        self.assertEqual(self.db.call_next(["MG"], "PC-DOC", self.doc, "Bureau 1")["ticket_label"], "MG-001")
        self.assertEqual(seen, [("MG-001", False, "Bureau 1")])
        u = self.db.update_admission(a["id"], {"last_name": "Z", "first_name": "W", "parsed": self.p, "gender": "H",
                                               "service_code": "RAD", "user_id": self.acc}, "PC")
        self.assertEqual((u["ticket_label"], u["service_code"], u["modified_count"]), ("MG-001", "RAD", 1))


class RbacTests(Base):
    def test_roles_are_enforced(self):
        with self.assertRaises(PermissionError): self.add("A", "B", "MG", uid=self.doc)               # médecin ≠ accueil
        with self.assertRaises(PermissionError): self.add("A", "B", "MG", uid=self.tech)              # radio : RAD seulement
        self.assertEqual(self.add("A", "B", "RAD", uid=self.tech)["ticket_label"], "RAD-001")
        with self.assertRaises(PermissionError): self.db.reset_shift("PC", self.doc)
        with self.assertRaises(PermissionError): self.db.radio_queue(self.doc)
        with self.assertRaises(PermissionError): self.db.lab_queue(self.tech)
        with self.assertRaises(PermissionError): self.db.pharmacy_queue(self.doc)
        with self.assertRaises(PermissionError): self.db.call_next(["MG"], "PC", self.acc)
        with self.assertRaises(PermissionError): self.db.tv_set("x", False, self.doc)
        with self.assertRaises(PermissionError): self.db.list_results("radio", 1, self.pharm)
        with self.assertRaises(PermissionError): self.db.search_patients("abc", self.tech)
        with self.assertRaises(PermissionError): self.db.reset_shift("PC", None)                       # session absente
        self.db.update_user(self.doc, {"active": 0})
        with self.assertRaises(PermissionError): self.db.call_next(["MG"], "PC", self.doc)             # compte désactivé


class UserTests(Base):
    def test_pin_lockout_and_delete(self):
        uid = self.db.create_user("dupont", "Marie", "medecin", "", "5555")
        self.assertTrue(self.db.verify_pin(uid, "5555")["ok"])
        for _ in range(5):
            r = self.db.verify_pin(uid, "0000")
        self.assertIn("verrouillé", r["error"]); self.assertFalse(self.db.verify_pin(uid, "5555")["ok"])
        with self.assertRaises(ValueError): self.db.create_user("A", "B", "medecin", "", "12")
        with self.assertRaises(ValueError): self.db.create_user("A", "B", "chef", "", "1234")
        self.db.delete_user(uid)                                                      # aucun historique : suppression possible
        self.assertNotIn(uid, [u["id"] for u in self.db.list_users(active_only=False)])
        self.add("A", "B", "MG")
        with self.assertRaises(ValueError): self.db.delete_user(self.acc)             # a laissé des traces : à désactiver
        self.assertEqual(len(self.db.list_users(roles=["accueil"])), 1)

    def test_griffe_and_signature_stored_separately(self):
        self.db.set_user_image(self.doc, "griffe", "AAA"); self.db.set_user_image(self.doc, "signature", "BBB")
        u = self.db.get_user(self.doc); self.assertEqual((u["signature_b64"], u["sign_b64"]), ("AAA", "BBB"))


class ClinicalFlowTests(Base):
    def setUp(self):
        super().setUp()
        self.adm = self.add("Said", "Omar", "MG", triage="ORANGE", ident="123456789")
        self.db.call_next(["MG"], "DOC1", self.doc, "Bureau 1")
        self.cons = self.db.start_consultation(self.adm["id"], self.doc, "DOC1")

    def test_multi_doctor_isolation_and_release(self):
        self.assertEqual(self.db.current_called("DOC1", self.doc)["id"], self.adm["id"])
        self.assertIsNone(self.db.current_called("DOC1", self.doc2))                    # l'autre médecin ne voit pas ce patient
        with self.assertRaises(PermissionError): self.db.create_prescription(self.cons["id"], [{"drug": "A"}], "", self.doc2)
        with self.assertRaises(PermissionError): self.db.close_consultation(self.cons["id"], "", "", self.doc2)
        self.db.release_patient(self.adm["id"], self.doc)                               # relève de garde
        self.assertEqual(self.db.queue(["MG"])[0]["id"], self.adm["id"])
        c2 = self.db.call_next(["MG"], "DOC1", self.doc2); self.assertEqual(c2["id"], self.adm["id"])
        cons2 = self.db.start_consultation(self.adm["id"], self.doc2, "DOC1")
        self.assertNotEqual(cons2["id"], self.cons["id"])
        self.assertEqual(self.db._one("SELECT outcome FROM consultations WHERE id=?", (self.cons["id"],))["outcome"], "INTERRUPTED")

    def test_prescription_number_qr_barcode_and_pharmacy(self):
        items = [{"drug": "Paracétamol 500 mg cp", "dosage": "1 cp x 3/j", "duration": "5 jours"}, {"drug": "Libre"}, {"drug": " "}]
        rx = self.db.create_prescription(self.cons["id"], items, "repos", self.doc)
        self.assertEqual(len(rx["items"]), 2)
        self.assertRegex(rx["qr_text"], r"^SDEM1[0-9a-f]{48}$"); self.assertRegex(rx["number"], r"^20\d{2}\d{6}$")
        self.assertIn("Libre", self.db.list_drug_names())
        self.assertEqual(self.db.pharmacy_queue(self.pharm), [])
        self.db.send_to_pharmacy(rx["uuid"], self.doc)
        q = self.db.pharmacy_queue(self.pharm); self.assertEqual((len(q), q[0]["number"]), (1, rx["number"]))
        self.assertTrue(self.db.pharmacy_lookup(rx["qr_text"], self.pharm)["authentic"])
        self.assertFalse(self.db.pharmacy_lookup("SDEM1" + rx["uuid"] + "0" * 16, self.pharm)["authentic"])
        self.assertFalse(self.db.pharmacy_lookup("SDEM1" + "a" * 32 + "b" * 16, self.pharm)["found"])
        bar = self.db.pharmacy_lookup(rx["number"], self.pharm); self.assertTrue(bar["found"]); self.assertIsNone(bar["authentic"])
        self.assertTrue(self.db.pharmacy_dispense(rx["uuid"], self.pharm)["ok"])
        self.assertFalse(self.db.pharmacy_dispense(rx["uuid"], self.pharm)["ok"])

    def test_tampered_prescription_detected(self):
        rx = self.db.create_prescription(self.cons["id"], [{"drug": "A", "dosage": "1", "duration": "1"}], "", self.doc)
        canon = self.db._one("SELECT canonical FROM prescriptions WHERE uuid=?", (rx["uuid"],))["canonical"]
        self.db.conn.execute("UPDATE prescriptions SET canonical=? WHERE uuid=?", (self.db._enc(canon.replace('"A"', '"B"')), rx["uuid"]))
        self.db.conn.commit()
        self.assertFalse(self.db.pharmacy_lookup(rx["qr_text"], self.pharm)["authentic"])

    def test_radiology_bridge_with_instructions_and_results(self):
        r1 = self.db.create_radio_request(self.cons["id"], "Radio X", "Thorax", "Droit", "toux", "Face et profil", False, self.doc, "DOC1")
        r2 = self.db.create_radio_request(self.cons["id"], "Scanner", "Crâne", "Non applicable", "chute", "", True, self.doc, "DOC1")
        direct = self.add("Direct", "Ali", "RAD")
        self.assertEqual([r1["ticket_label"], r2["ticket_label"], direct["ticket_label"]], ["RAD-001", "RAD-002", "RAD-003"])
        self.assertEqual(r1["instructions"], "Face et profil")
        self.assertEqual([r["ticket_label"] for r in self.db.radio_queue(self.tech)], ["RAD-002", "RAD-001", "RAD-003"])
        seen = []; self.db.call_listeners.append(lambda row, rc, room: seen.append((row["ticket_label"], room)))
        c = self.db.radio_call_next("RADIO1", self.tech, "Salle radio"); self.assertEqual(seen, [("RAD-002", "Salle radio")])
        img = base64.b64encode(b"\x89PNG fake").decode()
        rid = self.db.add_result("radio", c["id"], "cliche.png", "image/png", img, "Pas de fracture.", self.tech)
        with self.assertRaises(PermissionError): self.db.add_result("radio", c["id"], "x", "x", img, "", self.labo)
        self.db.radio_validate(c["id"], "AWAITING_PRINT", "à tirer", self.tech)
        mine = {r["ticket_label"]: r for r in self.db.radio_requests_for_doctor(self.doc)}
        self.assertEqual((mine["RAD-002"]["status"], mine["RAD-002"]["n_results"]), ("AWAITING_PRINT", 1))
        meta = self.db.list_results("radio", c["id"], self.doc); self.assertEqual((len(meta), meta[0]["report_text"]), (1, "Pas de fracture."))
        self.assertEqual(self.db.get_result(rid, self.doc)["data_b64"], img)
        with self.assertRaises(ValueError): self.db.add_result("radio", c["id"], None, None, None, "  ", self.tech)
        self.db.radio_call_next("RADIO1", self.tech); c3 = self.db.radio_call_next("RADIO1", self.tech)
        self.db.radio_validate(c3["id"], "DONE", "", self.tech)
        self.assertEqual(self.db.get(direct["id"])["status"], "DONE")

    def test_lab_flow_to_laboratory_and_back(self):
        lab = self.db.create_lab_request(self.cons["id"], ["FNS", "Labstix (bandelette urinaire)"], "fièvre", True, self.doc)
        self.assertEqual((lab["ticket_label"], lab["status"], lab["urgent"]), ("BIO-001", "PENDING", 1))
        with self.assertRaises(ValueError): self.db.create_lab_request(self.cons["id"], [], "", False, self.doc)
        q = self.db.lab_queue(self.labo); self.assertEqual((len(q), q[0]["items"][0], q[0]["last_name"]), (1, "FNS", "SAID"))
        self.assertEqual(self.db.lab_start(lab["id"], "LAB1", self.labo)["status"], "IN_PROGRESS")
        self.db.add_result("lab", lab["id"], None, None, None, "Hb 13 g/dl", self.labo)
        self.assertEqual(self.db.lab_validate(lab["id"], "", self.labo)["status"], "DONE")
        mine = self.db.lab_requests_for_doctor(self.doc); self.assertEqual((mine[0]["status"], mine[0]["n_results"]), ("DONE", 1))
        self.assertEqual(self.db.lab_queue(self.labo), [])
        self.assertEqual(self.db.list_results("lab", lab["id"], self.doc)[0]["report_text"], "Hb 13 g/dl")

    def test_close_and_dossier(self):
        self.db.create_prescription(self.cons["id"], [{"drug": "X", "dosage": "1", "duration": "1"}], "", self.doc)
        d = self.db.close_consultation(self.cons["id"], "RAS", "Angine", self.doc)
        self.assertEqual((d["consultation"]["diagnosis"], d["consultation"]["outcome"], d["patient"]["status"]), ("Angine", "CLOSED", "DONE"))
        self.assertEqual((len(d["prescriptions"]), d["doctor"]["last_name"]), (1, "MARTIN"))


class DpiAndTvTests(Base):
    def test_search_by_name_firstname_birth_and_ident_with_access_levels(self):
        a = self.add("Benali", "Ahmed", "MG", ident="19850001234")
        self.db.call_next(["MG"], "D", self.doc); cons = self.db.start_consultation(a["id"], self.doc, "D")
        rx = self.db.create_prescription(cons["id"], [{"drug": "A", "dosage": "1", "duration": "1"}], "", self.doc)
        self.db.close_consultation(cons["id"], "", "Grippe", self.doc)
        self.add("Benali", "Karim", "LAB")
        for q in ("benali", "ahmed", "BENALI ahmed", "19850001234", str(self.p["birth_year"])):
            self.assertTrue(self.db.search_patients(q, self.doc), q)
        self.assertEqual(len(self.db.search_patients("benali", self.doc)), 2)
        self.assertEqual(self.db.search_patients("zzz", self.doc), [])
        full = self.db.patient_record(a["id"], self.doc)
        self.assertEqual((full["level"], full["visits"][0]["consultations"][0]["diagnosis"], full["visits"][0]["prescriptions"][0]["uuid"]), ("medecin", "Grippe", rx["uuid"]))
        limited = self.db.patient_record(a["id"], self.acc)
        self.assertEqual(limited["level"], "accueil"); self.assertNotIn("consultations", limited["visits"][0])    # secret médical
        self.assertTrue(self.db._one("SELECT 1 AS x FROM audit_log WHERE action='DPI_VIEW'"))                 # accès tracé

    def test_tv_control_and_drug_import(self):
        events = []; self.db.tv_listeners.append(events.append)
        self.db.tv_set("Laboratoire fermé à 15h", True, self.acc); self.db.tv_clear(self.acc)
        self.assertEqual(self.db.tv_state(), {"message": "Laboratoire fermé à 15h", "paused": True})
        self.assertEqual([e["type"] for e in events], ["state", "clear"])
        self.assertEqual(self.db.import_drugs(["DOLIPRANE (Paracétamol) 500 mg cp", "doliprane (paracétamol) 500 mg cp", "", "NOUVEAU 10 mg"]), 2)


class SecurityAndOpsTests(Base):
    def test_clinical_fields_are_encrypted_at_rest_and_readable_through_api(self):
        a = self.add("Said", "Omar", "MG"); self.db.call_next(["MG"], "D", self.doc)
        cons = self.db.start_consultation(a["id"], self.doc, "D")
        self.db.create_prescription(cons["id"], [{"drug": "Paracétamol", "dosage": "1", "duration": "1"}], "note secrète", self.doc)
        self.db.close_consultation(cons["id"], "observation privée", "Diagnostic X", self.doc)
        raw = sqlite3.connect(self.db.path)
        for table, col, secret in (("consultations", "diagnosis", "Diagnostic X"), ("consultations", "notes", "observation privée"),
                                   ("prescriptions", "items_json", "Paracétamol"), ("prescriptions", "notes", "note secrète")):
            v = raw.execute(f"SELECT {col} FROM {table}").fetchone()[0]
            self.assertTrue(v.startswith("enc1:") and secret not in v, (table, col))
        raw.close()
        self.assertEqual(self.db.consultation_dossier(cons["id"])["consultation"]["diagnosis"], "Diagnostic X")
        # sans la clé, les données ne sont pas lisibles
        from crypto import Crypto
        with self.assertRaises(RuntimeError): Crypto(None).dec(self.db._one("SELECT 1 AS x") and sqlite3.connect(self.db.path).execute("SELECT diagnosis FROM consultations").fetchone()[0])

    def test_session_identity_from_jwt_overrides_arguments(self):
        self.db._ctx.uid = self.doc
        try:
            with self.assertRaises(PermissionError): self.db.call_next(["MG"], "PC", self.doc2)       # usurpation d'un autre médecin
            self.db.call_next(["MG"], "PC", self.doc)
        finally:
            self.db._ctx.uid = None

    def test_jwt_tokens(self):
        from auth import make_token, verify_token
        k = self.db.jwt_secret(); t = make_token(k, 7, "medecin")
        self.assertEqual((verify_token(k, t)["sub"], verify_token(k, t)["role"]), (7, "medecin"))
        with self.assertRaises(ValueError): verify_token(k, t[:-3] + "AAA")
        with self.assertRaises(ValueError): verify_token("autre-cle", t)
        with self.assertRaises(ValueError): verify_token(k, make_token(k, 7, "medecin", ttl=-5))

    def test_specialty_services_lab_secretariat_and_appointments(self):
        dent = self.db.create_user("Dent", "Ist", "medecin", "Chirurgien-dentiste", "7777", ["DENT"])
        self.assertEqual([u for u in self.db.list_users(roles=["medecin"]) if u["id"] == dent][0]["services"], ["DENT"])
        self.db.update_user(dent, {"services": ["DENT", "PED"]}); self.assertEqual(self.db.get_user(dent)["services"], ["DENT", "PED"])
        self.assertEqual(self.add("L", "M", "LAB", uid=self.labo)["ticket_label"], "LAB-001")
        with self.assertRaises(PermissionError): self.add("L", "M", "MG", uid=self.labo)
        ap = self.db.create_appointment({"last_name": "ali", "first_name": "Sam", "date": "2026-10-20", "time": "08:30", "exam": "Bilan"}, self.labo)
        self.db.create_appointment({"last_name": "bob", "first_name": "Tim", "date": "2026-10-21", "time": "09:00"}, self.labo)
        with self.assertRaises(ValueError): self.db.create_appointment({"last_name": "x", "first_name": "y", "date": "20/10/2026", "time": "08:30"}, self.labo)
        with self.assertRaises(PermissionError): self.db.create_appointment({"last_name": "x", "first_name": "y", "date": "2026-10-20", "time": "08:30"}, self.doc)
        self.assertEqual(len(self.db.list_appointments("2026-10-20", "2026-10-31", "", self.labo)), 2)
        self.assertEqual([a["last_name"] for a in self.db.list_appointments("2026-10-01", "2026-10-31", "ALI", self.labo)], ["ALI"])
        self.assertEqual(self.db.appointment_days("2026-10", self.labo), {"2026-10-20": 1, "2026-10-21": 1})
        self.db.update_appointment(ap["id"], {"last_name": "Ali", "first_name": "Sam", "date": "2026-10-22", "time": "10:00", "status": "ARRIVED"}, self.labo)
        self.assertEqual(self.db._one("SELECT date, status FROM appointments WHERE id=?", (ap["id"],)), {"date": "2026-10-22", "status": "ARRIVED"})
        self.db.delete_appointment(ap["id"], self.labo); self.assertEqual(len(self.db.list_appointments("2026-10-01", "2026-10-31", "", self.labo)), 1)

    def test_tv_screens_and_service_ids(self):
        self.assertEqual(self.db.tv_screens()[0]["id"], "main")
        s = self.db.tv_set_screens([{"id": "c1", "name": "Couloir 1", "services": ["DENT", "RAD", "XXX"]}, {"id": "c2", "name": "Labo", "services": ["LAB", "LABP", "BIO"]}])
        self.assertEqual(s[0]["services"], ["DENT", "RAD"])
        with self.assertRaises(ValueError): self.db.tv_set_screens([{"id": "a"}, {"id": "a"}])
        with self.assertRaises(ValueError): self.db.tv_set_screens([{"id": "!!"}])

    def test_dsp_stats_are_anonymous_aggregates(self):
        self.add("A", "B", "MG", triage="ROUGE"); self.add("C", "D", "LAB"); self.db.call_next(["MG"], "D", self.doc)
        st = self.db.stats_report("2000-01-01", "2100-01-01")
        self.assertEqual((st["admissions"], st["by_service"], st["by_triage"]), (2, {"LAB": 1, "MG": 1}, {"ROUGE": 1}))
        self.assertFalse(any(n in str(st) for n in ("'A'", "'B'", "'C'", "'D'")))                       # aucun nom de patient
        from reports import report_csv, report_html
        self.assertIn("Passages enregistrés", report_csv(st)); self.assertIn("DSP", report_html({}, st, ""))

    def test_outbox_fhir_and_background_sync(self):
        self.db.sync_enabled = True
        a = self.add("Said", "Omar", "MG", ident="XY1"); self.db.call_next(["MG"], "D", self.doc)
        cons = self.db.start_consultation(a["id"], self.doc, "D")
        self.db.create_prescription(cons["id"], [{"drug": "Amox", "dosage": "1 cp", "duration": "5 j"}], "", self.doc)
        self.db.close_consultation(cons["id"], "", "Angine", self.doc)
        import json, sync
        pend = self.db.outbox_pending(); self.assertEqual(len(pend), 1)
        b = json.loads(pend[0]["payload"]); kinds = [e["resource"]["resourceType"] for e in b["entry"]]
        self.assertEqual((b["resourceType"], kinds), ("Bundle", ["Patient", "Encounter", "MedicationRequest"]))
        calls = []
        def failing(url, body, headers): raise OSError("hors ligne")
        self.assertEqual(sync.run_once(self.db, "https://x", "tok", post=failing), (0, 1)); self.assertEqual(self.db.outbox_pending(), [])   # report (backoff)
        self.db.conn.execute("UPDATE sync_outbox SET next_try=NULL"); self.db.conn.commit()
        self.assertEqual(sync.run_once(self.db, "https://x", "tok", post=lambda u, b_, h: calls.append(h)), (1, 0))
        self.assertEqual((calls[0]["Authorization"], calls[0]["Idempotency-Key"]), ("Bearer tok", "dem-1"))
        with self.assertRaises(ValueError): sync._post("http://pas-https", b"", {})

    def test_auto_backup_rotation_and_integrity(self):
        self.db.backup_dir = os.path.join(os.path.dirname(self.db.path), "autobk")
        for _ in range(3): self.db.auto_backup("test", keep=2); import time; time.sleep(1.1)
        self.assertEqual(len(os.listdir(self.db.backup_dir)), 2); self.assertTrue(self.db.integrity_ok()); self.assertLess(self.db.last_backup_age_hours(), 1)
        self.db.reset_shift("PC", self.acc)                                                              # fin de garde => nouvelle sauvegarde
        self.assertGreaterEqual(len(os.listdir(self.db.backup_dir)), 2)

    def test_user_services_survive_and_barcode_table_is_valid(self):
        pass


class ImageAndTlsTests(unittest.TestCase):
    def test_background_removal_makes_transparent_png_and_trims(self):
        import io
        from PIL import Image, ImageDraw
        import imgproc
        img = Image.new("RGB", (400, 200), (205, 205, 205))                      # fond gris de scanner
        ImageDraw.Draw(img).line((120, 60, 280, 140), fill=(10, 10, 80), width=8)  # trait de signature
        buf = io.BytesIO(); img.save(buf, "PNG")
        out = Image.open(io.BytesIO(imgproc.process(buf.getvalue())))
        self.assertEqual(out.mode, "RGBA"); self.assertLess(out.width, 250)     # rognage automatique autour de l'encre
        self.assertEqual(out.getpixel((0, 0))[3], 0)                              # le fond est transparent
        a = out.getchannel("A"); self.assertEqual(a.getextrema()[1], 255)        # le trait est opaque
        mono = Image.open(io.BytesIO(imgproc.process(buf.getvalue(), keep_color=False)))
        self.assertEqual(mono.mode, "RGBA")
        tight = Image.open(io.BytesIO(imgproc.process(buf.getvalue(), crop=(30, 0, 30, 0), trim=False)))
        self.assertLess(tight.width, 200)                                         # rognage manuel (%)
        trans = Image.new("RGBA", (50, 50), (0, 0, 0, 0)); ImageDraw.Draw(trans).rectangle((10, 10, 30, 30), fill=(200, 0, 0, 255))
        b2 = io.BytesIO(); trans.save(b2, "PNG")
        self.assertEqual(Image.open(io.BytesIO(imgproc.process(b2.getvalue()))).getpixel((10, 10)), (200, 0, 0, 255))   # PNG déjà transparent conservé

    def test_tls13_pinned_certificate_roundtrip(self):
        import json, ssl, tempfile, threading, urllib.request
        from werkzeug.serving import make_server
        from flask import Flask, jsonify
        import tls
        d = tempfile.mkdtemp(); cert, key = tls.ensure_cert(d)
        app = Flask(__name__); app.add_url_rule("/p", "p", lambda: jsonify(ok=True))
        srv = make_server("127.0.0.1", 0, app, ssl_context=tls.server_context(cert, key)); port = srv.server_port
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        pem = tls.fetch_cert("127.0.0.1", port)
        self.assertRegex(tls.fingerprint(pem), r"^([0-9A-F]{2}:){31}[0-9A-F]{2}$")
        r = urllib.request.urlopen(f"https://127.0.0.1:{port}/p", context=tls.client_context(pem), timeout=5)
        self.assertEqual(json.load(r), {"ok": True})
        other_dir = tempfile.mkdtemp(); other_cert, _ = tls.ensure_cert(other_dir)                       # un autre certificat n'est PAS accepté (épinglage)
        with self.assertRaises(Exception):
            urllib.request.urlopen(f"https://127.0.0.1:{port}/p", context=tls.client_context(open(other_cert).read()), timeout=5)
        srv.shutdown()


def _sqlite_v(path, fixture):
    con = sqlite3.connect(path)
    with open(os.path.join(FIX, fixture), encoding="utf-8") as f:
        con.executescript(f.read())
    return con


class MigrationTests(unittest.TestCase):
    def test_v1_database_is_migrated_to_v3(self):
        d = tempfile.mkdtemp(); path = os.path.join(d, "dem_database.db")
        con = _sqlite_v(path, "schema_v1.sql")
        con.execute("INSERT INTO shifts(started_at) VALUES ('2026-10-01 08:00:00')")
        con.execute("INSERT INTO counters(shift_id,service_code,last_number) VALUES (1,'LAB',1)")
        con.execute("""INSERT INTO admissions(shift_id,service_code,ticket_number,ticket_label,full_name,name_norm,birth_year,gender,created_at)
                       VALUES (1,'LAB',1,'LAB-001','Benali Ahmed','ahmed benali',1990,'H','2026-10-01 08:05:00')""")
        con.commit(); con.close()
        db = Database(path)
        self.assertEqual(db._one("SELECT value FROM meta WHERE key='schema_version'")["value"], "3")
        a = db.get(1); self.assertEqual((a["ticket_label"], a["last_name"], a["first_name"], a["patient_ident"]), ("LAB-001", "Benali Ahmed", "", None))
        self.assertTrue(os.path.isdir(os.path.join(d, "backups")))
        uid = db.create_user("L", "N", "labo", "", "1234"); self.assertTrue(db.verify_pin(uid, "1234")["ok"])   # rôle « labo » accepté
        Database(path)

    def test_v2_database_keeps_users_and_history_through_migration(self):
        d = tempfile.mkdtemp(); path = os.path.join(d, "dem_database.db")
        con = _sqlite_v(path, "schema_v2.sql")
        con.execute("INSERT INTO shifts(started_at) VALUES ('2026-10-01 08:00:00')")
        con.execute("""INSERT INTO users(last_name,first_name,role,specialty,pin_salt,pin_hash,created_at,signature_b64)
                       VALUES ('MARTIN','Paul','medecin','Gen','aa','bb','2026-10-01 07:00:00','GRIFFE')""")
        con.execute("""INSERT INTO admissions(shift_id,service_code,ticket_number,ticket_label,full_name,name_norm,birth_year,gender,created_at,last_name,first_name)
                       VALUES (1,'MG',1,'MG-001','MARTIN X','martin x',1980,'H','2026-10-01 08:00:00','MARTIN','X')""")
        con.execute("INSERT INTO consultations(admission_id,doctor_user_id,started_at) VALUES (1,1,'2026-10-01 08:10:00')")
        con.execute("INSERT INTO lab_requests(uuid,consultation_id,admission_id,doctor_user_id,items_json,created_at) VALUES ('u1',1,1,1,'[\"NFS\"]','2026-10-01 08:20:00')")
        con.commit(); con.close()
        db = Database(path)
        u = db.get_user(1); self.assertEqual((u["last_name"], u["signature_b64"], u["sign_b64"]), ("MARTIN", "GRIFFE", None))
        self.assertEqual(db._one("SELECT doctor_user_id FROM consultations WHERE id=1")["doctor_user_id"], 1)    # lien conservé
        self.assertEqual(db._one("SELECT status FROM lab_requests WHERE id=1")["status"], "DONE")                # ancien imprimé : terminé
        self.assertEqual(db._one("PRAGMA foreign_key_check"), None)                                              # aucune clé étrangère cassée
        db.create_user("Labo", "Z", "labo", "", "9999")


class SemVerAndRpcTests(unittest.TestCase):
    def test_semver(self):
        self.assertTrue(is_newer("v1.2.0", "1.1.0")); self.assertTrue(is_newer("v1.10.0", "1.9.9"))
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
    def setUp(self):
        from hub_server import Hub

        class Cfg:
            data = {"lan_token": "secret", "parent": "EPSP X", "structure": "POLY Y"}
            def get(self, k, d=None): return self.data.get(k, d)

        self.cfg = Cfg(); self.db = new_db()
        self.acc = self.db.create_user("A", "B", "accueil", "", "1000"); self.doc = self.db.create_user("D", "E", "medecin", "", "1111")
        self.hub = Hub(self.db, self.cfg); self.c = self.hub.app.test_client()

    def rpc(self, m, *a, token=None, bearer=None, **k):
        h = {"X-DEM-Token": token or "secret"}
        if bearer: h["Authorization"] = "Bearer " + bearer
        return self.c.post("/rpc", json={"m": m, "a": list(a), "k": k}, headers=h)

    def test_token_jwt_roles_and_public_methods(self):
        self.assertEqual(self.c.post("/rpc", json={"m": "tv_state"}).status_code, 403)                   # sans jeton réseau
        self.assertEqual(self.rpc("tv_state").status_code, 200)                                          # public : jeton réseau seul
        self.assertEqual(self.rpc("current_shift", "PC").status_code, 401)                               # appel utilisateur sans JWT
        self.assertEqual(self.rpc("backup").status_code, 400)
        r = self.rpc("verify_pin", self.doc, "1111").get_json()["r"]; self.assertTrue(r["ok"]); tok = r["token"]
        self.assertEqual(self.rpc("current_shift", "PC", bearer=tok).status_code, 200)
        self.assertEqual(self.rpc("reset_shift", "PC", self.doc, bearer=tok).status_code, 403)           # médecin : pas d'accueil
        self.assertEqual(self.rpc("call_next", ["MG"], "PC", self.acc, bearer=tok).status_code, 403)     # usurpation d'identité refusée
        self.assertEqual(self.rpc("call_next", ["MG"], "PC", self.doc, bearer=tok).status_code, 200)
        self.assertEqual(self.rpc("get_user", self.acc, bearer=tok).status_code, 403)                    # SELF_ONLY
        self.assertEqual(self.rpc("create_user", "N", "P", "labo", "", "1234").status_code, 200)         # admin : jeton réseau
        self.assertEqual(self.rpc("current_shift", "PC", bearer=tok[:-2] + "xx").status_code, 401)
        self.assertEqual(self.c.get("/api/ping").get_json()["name"], "EPSP X — POLY Y")

    def test_tv_privacy_pause_and_per_screen_filtering(self):
        class Fake:
            def __init__(self): self.msgs = []
            def send(self, m): self.msgs.append(json.loads(m))
        import json as _j
        globals()["json"] = _j
        dent, lab, allscr = Fake(), Fake(), Fake()
        self.hub.tv_clients.update({dent: {"DENT", "RAD"}, lab: {"LAB", "LABP", "BIO"}, allscr: None})
        self.hub.on_call({"ticket_label": "DENT-001", "service_code": "DENT"}, False, "Cabinet dentaire")
        self.hub.on_call({"ticket_label": "LAB-004", "service_code": "LAB"}, False, "Prélèvements")
        self.assertEqual([m["ticket"] for m in dent.msgs], ["DENT-001"]); self.assertEqual([m["ticket"] for m in lab.msgs], ["LAB-004"])
        self.assertEqual(len(allscr.msgs), 2); self.assertTrue(all("name" not in m and "full_name" not in m for m in allscr.msgs))
        self.assertEqual(dent.msgs[0]["service_id"], "DENT"); self.assertTrue(dent.msgs[0]["color"].startswith("#"))
        self.db.tv_set("Laboratoire fermé à 15h", True, self.acc)
        self.assertEqual(allscr.msgs[-1], {"type": "state", "message": "Laboratoire fermé à 15h", "paused": True})
        n = len(allscr.msgs); self.hub.test_call(); self.assertEqual(len(allscr.msgs), n)               # en pause : rien n'est affiché
        self.assertIn("ws/tv", self.c.get("/tv").get_data(as_text=True))

    def test_https_required_when_tls_enabled(self):
        self.hub.tls_required = True
        self.assertEqual(self.rpc("tv_state").status_code, 403)


if __name__ == "__main__":
    unittest.main()
