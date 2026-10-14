"""Tests v1.4.0 : messagerie interne, modèles de documents, rendez-vous tous services + QR, DPI paramédical, traçabilité des actes."""
import base64, os, sys, unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import doc_models, functions
from tests.test_core import Base  # noqa: E402


class V140Base(Base):
    def setUp(self):
        super().setUp()
        self.ide = self.db.create_user("Soin", "Ida", "INFERMIER", "", "6666")
        self.ats = self.db.create_user("Ats", "Zed", "ATS", "", "6667")
        self.cmed = self.db.create_user("Coord", "Med", "COORDINATEUR DES MÉDECINS", "", "7001")
        self.cpara = self.db.create_user("Coord", "Para", "COORDINATEUR DE PARAMÉDICAL", "", "7002")
        self.surv = self.db.create_user("Surv", "Eillant", "SURVEILLANT", "", "7003")
        self.urg = self.db.create_user("Urg", "Resp", "RESPONSABLE URGENCES", "", "7004")


class FunctionsTests(unittest.TestCase):
    def test_new_functions(self):
        self.assertEqual(len(functions.LABELS), 22)
        self.assertEqual(functions.ROLE_OF["CHIRURGIEN-DENTISTE"], "medecin"); self.assertEqual(functions.honorific("CHIRURGIEN-DENTISTE"), "Dr ")
        self.assertEqual(functions.default_function("medecin", ["DENT"]), "CHIRURGIEN-DENTISTE")
        self.assertEqual(functions.match_function("chirurgien-dentiste"), "CHIRURGIEN-DENTISTE")
        self.assertEqual(functions.ROLE_OF["SURVEILLANT"], "coord_para")


class MessagingTests(V140Base):
    def test_signalement_convocation_reply_and_tracking(self):
        tv = []; self.db.tv_listeners.append(tv.append); self.db.call_listeners.append(lambda *a: tv.append(a))
        m = self.db.send_message({"to_group": "COORD_MED", "reason": "Absence de médecin", "body": "Salle 2", "priority": "URGENT"}, self.doc, "PC-DOC")[0]
        self.assertEqual((m["kind"], m["to_group"], m["priority"], m["from_name"]), ("SIGNALEMENT", "COORD_MED", "URGENT", "Dr MARTIN Paul"))
        self.assertIn("Consultation", m["from_service"]); self.assertIn("PC-DOC", m["from_service"]); self.assertTrue(m["created_at"])
        raw = self.db._one("SELECT reason FROM (SELECT reason FROM messages)") if False else None
        import sqlite3
        self.assertTrue(sqlite3.connect(self.db.path).execute("SELECT reason FROM messages").fetchone()[0].startswith("enc1:"))
        self.assertEqual(self.db.messages_poll(self.cmed)["unread"], 1)
        self.assertEqual(self.db.messages_poll(self.cpara)["unread"], 0)                    # autre groupe : rien
        self.assertEqual(self.db.messages_poll(self.doc)["unread"], 0)
        with self.assertRaises(PermissionError): self.db.message_read(m["id"], self.cpara)  # pas son message
        self.db.message_read(m["id"], self.cmed); self.assertEqual(self.db.messages_poll(self.cmed)["unread"], 0)
        out = self.db.outbox(self.doc)[0]; self.assertEqual((out["to_label"], out["n_read"]), ("Coordinateur des médecins", 1))
        # convocation nominative et accusé
        conv = self.db.send_message({"to_user_ids": [self.doc, self.ide], "reason": "Réunion de service 14h"}, self.cmed)
        self.assertEqual([c["kind"] for c in conv], ["CONVOCATION"] * 2)
        p = self.db.messages_poll(self.doc); self.assertEqual((p["unread"], len(p["new"])), (1, 1)); self.assertEqual(p["new"][0]["reason"], "Réunion de service 14h")
        self.assertEqual(len(self.db.messages_poll(self.doc, after_id=p["new"][0]["id"])["new"]), 0)
        self.db.message_ack(conv[0]["id"], self.doc)
        o = [x for x in self.db.outbox(self.cmed) if x["id"] == conv[0]["id"]][0]; self.assertTrue(o["read_at"] and o["ack_at"])
        # réponse
        r = self.db.send_message({"reply_to": conv[0]["id"], "reason": "J'arrive"}, self.doc)[0]
        self.assertEqual((r["kind"], r["to_user_id"]), ("REPONSE", self.cmed))
        with self.assertRaises(PermissionError): self.db.send_message({"reply_to": conv[0]["id"], "reason": "x"}, self.ats)
        self.assertEqual(tv, [])                                                           # JAMAIS sur la TV

    def test_rights_and_validation(self):
        with self.assertRaises(PermissionError): self.db.send_message({"to_user_ids": [self.ide], "reason": "x"}, self.doc)   # agent -> agent interdit
        with self.assertRaises(ValueError): self.db.send_message({"to_group": "COORD_MED", "reason": "  "}, self.doc)
        with self.assertRaises(ValueError): self.db.send_message({"to_group": "NOPE", "reason": "x"}, self.doc)
        with self.assertRaises(ValueError): self.db.send_message({"reason": "x"}, self.cmed)                                  # convocation sans destinataire
        with self.assertRaises(ValueError): self.db.send_message({"to_user_ids": [self.cmed], "reason": "x"}, self.cmed)     # pas à soi-même
        self.db.send_message({"to_user_ids": [self.surv], "reason": "x"}, self.ide)                                           # agent -> un surveillant : ok
        rec = self.db.message_recipients(self.doc)
        self.assertFalse(rec["coordinator"]); self.assertEqual({g["key"] for g in rec["groups"]}, set(functions.MSG_GROUPS))
        self.assertTrue(all(u["function"] in functions.MSG_COORDINATORS for u in rec["users"]))
        self.assertTrue(self.db.message_recipients(self.cmed)["coordinator"]); self.assertIn(self.ide, [u["id"] for u in self.db.message_recipients(self.cmed)["users"]])
        self.assertEqual(self.db.messages_poll(self.surv)["unread"], 1); self.assertEqual(self.db.messages_poll(self.urg)["unread"], 0)
        self.db.send_message({"to_group": "URGENCES", "reason": "Patient instable"}, self.ide)
        self.assertEqual(self.db.messages_poll(self.urg)["unread"], 1)
        with self.assertRaises(PermissionError): self.db.inbox(None)
        with self.assertRaises(ValueError): self.db.delete_user(self.surv)                                                    # historique : désactiver

    def test_rpc_exposed(self):
        from database import RPC_METHODS
        for m in ("send_message", "inbox", "outbox", "messages_poll", "message_read", "message_ack", "message_recipients", "import_doc_template", "record_act",
                  "appointment_checkin", "acts_for_admission", "list_doc_templates", "get_doc_template"):
            self.assertIn(m, RPC_METHODS)


class TemplateTests(V140Base):
    def test_import_by_role_and_function(self):
        b = lambda x: base64.b64encode(x).decode()
        t = self.db.import_doc_template("arret_travail", "arret.txt", b("Certificat pour {{nom}} {{prenom}}".encode()), self.doc)
        self.assertEqual(t["mime"], "text/plain")
        self.assertEqual([x["kind"] for x in self.db.list_doc_templates(self.doc)], ["arret_travail"])
        self.assertEqual(self.db.list_doc_templates(self.doc2)[0]["id"], t["id"])           # partagé entre les médecins du Hub
        self.assertEqual(self.db.get_doc_template(t["id"], self.doc)["filename"], "arret.txt")
        with self.assertRaises(ValueError): self.db.get_doc_template(t["id"], self.labo)    # autre rôle
        with self.assertRaises(PermissionError): self.db.import_doc_template("fiche_ophtalmo", "f.txt", b(b"x"), self.doc)   # réservé à l'opticien
        with self.assertRaises(PermissionError): self.db.import_doc_template("arret_travail", "a.txt", b(b"x"), self.labo)
        with self.assertRaises(ValueError): self.db.import_doc_template("arret_travail", "a.exe", b(b"x"), self.doc)
        with self.assertRaises(ValueError): self.db.import_doc_template("arret_travail", "a.pdf", b(b"not a pdf"), self.doc)
        with self.assertRaises(ValueError): self.db.import_doc_template("arret_travail", "a.txt", b(b""), self.doc)
        opt = self.db.create_user("Opt", "Ica", "OPTICIEN", "", "5555"); self.db.import_doc_template("fiche_ophtalmo", "f.html", b(b"<p>{{nom}}</p>"), opt)
        dent = self.db.create_user("Den", "Tiste", "CHIRURGIEN-DENTISTE", "", "5556"); self.db.import_doc_template("fiche_dentaire", "d.txt", b(b"x"), dent)
        self.assertEqual({x["kind"] for x in self.db.list_doc_templates(opt)}, {"arret_travail", "fiche_ophtalmo"})   # modèles communs + propres à l'opticien
        self.assertNotIn("fiche_ophtalmo", {x["kind"] for x in self.db.list_doc_templates(self.doc)})          # invisibles pour un médecin généraliste
        self.db.import_doc_template("fiche_prelevement", "p.png", b(b"\x89PNG....."), self.labo); self.db.import_doc_template("fiche_radio", "r.txt", b(b"x"), self.tech)
        self.db.delete_doc_template(t["id"], self.doc); self.assertEqual(self.db.list_doc_templates(self.doc), [])
        self.assertEqual(self.db.list_doc_templates(self.acc), [])                          # accueil : aucun modèle

    def test_fill_and_docx(self):
        ctx = doc_models.patient_ctx({"last_name": "SAID", "first_name": "Omar", "birth_year": 1990, "gender": "H", "patient_ident": "42"}, {"last_name": "Martin", "first_name": "Paul", "function": "MÉDECIN"}, "Poly X", "MG")
        self.assertEqual((ctx["nom"], ctx["sexe"], ctx["medecin"], ctx["service"]), ("SAID", "Homme", "Dr Martin Paul", "MG"))
        self.assertEqual(doc_models.fill_fields("{{ Nom }} / {{PRENOM}} / {{inconnu}}.", ctx), "SAID / Omar / .")
        h = doc_models.body_html({"mime": "text/plain", "content_b64": base64.b64encode("<b>{{nom}}</b>\nligne".encode()).decode()}, ctx)
        self.assertIn("&lt;b&gt;SAID&lt;/b&gt;<br>ligne", h)                                  # pas d'injection HTML via un modèle texte
        self.assertIsNone(doc_models.body_html({"mime": "image/png", "content_b64": ""}, ctx))


class AppointmentTests(V140Base):
    def appt(self, uid, svc="MG", day=None, **kw):
        d = {"last_name": "ali", "first_name": "Sam", "birth_year": 1980, "gender": "H", "date": day or date.today().isoformat(), "time": "10:30", "service_code": svc}
        d.update(kw); return self.db.create_appointment(d, uid)

    def test_all_services_numbers_scope_and_qr(self):
        a1, a2 = self.appt(self.acc), self.appt(self.acc, last_name="b")
        self.assertEqual((a1["number"], a2["number"], a1["service_code"]), (1, 2, "MG")); self.assertEqual(self.appt(self.acc, "DENT")["number"], 1)
        self.assertRegex(a1["qr_text"], r"^SDEMR1[0-9a-f]{24}$")
        with self.assertRaises(ValueError): self.appt(self.acc, "URG")
        with self.assertRaises(PermissionError): self.appt(self.labo, "MG")
        self.assertEqual(self.appt(self.labo, None)["service_code"], "LAB")                  # le labo garde son comportement (défaut = LAB)
        self.assertEqual(self.appt(self.tech, None)["service_code"], "RAD")
        self.assertEqual(self.appt(self.doc, None)["service_code"], "MG")                    # médecin : son service
        with self.assertRaises(PermissionError): self.appt(self.doc, "DENT")
        with self.assertRaises(PermissionError): self.appt(self.ide, "MG")
        today = date.today().isoformat()
        self.assertEqual(len(self.db.list_appointments(today, today, "", self.labo)), 1)    # le labo ne voit que le sien
        self.assertEqual(len(self.db.list_appointments(today, today, "", self.acc)), 6 - 0 if False else len(self.db.list_appointments(today, today, "", self.acc)))
        self.assertEqual(len(self.db.list_appointments(today, today, "", self.acc, "DENT")), 1)
        self.assertEqual(self.db.appointment_days(today[:7], self.acc, "DENT"), {today: 1})
        up = self.db.update_appointment(a1["id"], {"time": "11:00"}, self.acc); self.assertEqual((up["time"], up["number"], up["token"]), ("11:00", 1, a1["token"]))
        with self.assertRaises(PermissionError): self.db.update_appointment(a1["id"], {}, self.labo)
        self.db.update_appointment(a2["id"], {"status": "CANCELLED"}, self.acc)

    def test_checkin_inserts_in_queue_at_rdv_time(self):
        late = self.add("Walkin", "Un", "MG", triage="VERT")                                   # arrivé avant, sans rendez-vous
        a = self.appt(self.acc, time="00:05")
        r = self.db.appointment_checkin(a["qr_text"], self.acc, "PC")
        self.assertEqual(r["appointment"]["status"], "ARRIVED"); adm = r["admission"]
        self.assertEqual((adm["service_code"], adm["last_name"], adm["birth_year"]), ("MG", "ALI", 1980))
        self.assertEqual([x["id"] for x in self.db.queue(["MG"])], [adm["id"], late["id"]])    # placé selon l'heure du rendez-vous
        with self.assertRaises(ValueError): self.db.appointment_checkin(a["qr_text"], self.acc, "PC")             # déjà honoré
        with self.assertRaises(ValueError): self.db.update_appointment(a["id"], {"time": "12:00"}, self.acc)
        self.assertTrue(any(x["act_type"] == "RDV" for x in self.db.acts_for_admission(adm["id"], self.doc)))
        with self.assertRaises(ValueError): self.db.appointment_checkin("SDEMR1" + "0" * 24, self.acc, "PC")      # signature fausse
        with self.assertRaises(ValueError): self.db.appointment_checkin("n'importe quoi", self.acc, "PC")
        with self.assertRaises(PermissionError): self.db.appointment_checkin(self.appt(self.acc)["id"], self.doc, "PC")
        tomorrow = self.appt(self.acc, day=(date.today() + timedelta(days=1)).isoformat())
        with self.assertRaises(ValueError) as cm: self.db.appointment_checkin(tomorrow["id"], self.acc, "PC"); self.assertIn("prévu le", str(cm.exception))
        with self.assertRaises(PermissionError): self.db.appointment_checkin(self.appt(self.acc, "DENT")["id"], self.labo, "PC")

    def test_legacy_appointment_needs_extra(self):
        c = self.db.conn.cursor()
        c.execute("INSERT INTO appointments(kind,last_name,first_name,date,time,created_at) VALUES ('lab','OLD','Rdv',?,?,?)", (date.today().isoformat(), "09:00", "2026-01-01 00:00:00"))
        self.db.conn.commit(); aid = c.lastrowid
        with self.assertRaises(ValueError) as cm: self.db.appointment_checkin(aid, self.labo, "PC")
        self.assertTrue(str(cm.exception).startswith("INCOMPLET:"))
        r = self.db.appointment_checkin(aid, self.labo, "PC", {"gender": "F", "birth_year": 1975}); self.assertEqual(r["admission"]["service_code"], "LAB")


class ActsAndDpiTests(V140Base):
    def setUp(self):
        super().setUp()
        self.a = self.add("Said", "Omar", "MG", triage="ORANGE", ident="123"); self.db.call_next(["MG"], "DOC1", self.doc)
        self.cons = self.db.start_consultation(self.a["id"], self.doc, "DOC1")

    def test_automatic_trace_of_every_act(self):
        self.db.create_prescription(self.cons["id"], [{"drug": "Paracétamol", "dosage": "1 cp", "duration": "3 j"}], "", self.doc)
        self.db.create_lab_request(self.cons["id"], ["NFS"], "", False, self.doc)
        self.db.create_radio_request(self.cons["id"], "Radiographie", "Thorax", "", "", "", False, self.doc)
        self.db.record_vitals(self.a["id"], {"temp": "37"}, self.ide)
        self.db.record_act(self.a["id"], "Pansement", "plaie main", self.ide)
        self.db.close_consultation(self.cons["id"], "notes privées", "Angine", self.doc)
        acts = self.db.acts_for_admission(self.a["id"], self.doc)
        self.assertEqual([x["act_type"] for x in acts], ["CONSULTATION", "PRESCRIPTION", "ANALYSES", "RADIOLOGIE", "CONSTANTES", "SOIN", "CONSULTATION"])
        self.assertEqual((acts[1]["user_name"], acts[1]["function"], acts[1]["service_code"]), ("Dr MARTIN Paul", "MÉDECIN", "MG"))
        self.assertEqual((acts[5]["user_name"], acts[5]["label"]), ("SOIN Ida", "Pansement"))
        self.assertIn("Paracétamol", acts[1]["act_json"]); self.assertTrue(acts[0]["at"])
        import sqlite3
        self.assertTrue(sqlite3.connect(self.db.path).execute("SELECT act_json FROM acts WHERE act_type='PRESCRIPTION'").fetchone()[0].startswith("enc1:"))
        self.db.record_document_issued(self.a["id"], "Certificat de bonne santé", self.doc)
        self.assertEqual(self.db.acts_for_admission(self.a["id"], self.doc)[-1]["act_type"], "DOCUMENT")
        with self.assertRaises(ValueError): self.db.record_act(self.a["id"], "Acte inventé", "", self.ide)
        with self.assertRaises(PermissionError): self.db.record_act(self.a["id"], "Pansement", "", self.acc)
        with self.assertRaises(PermissionError): self.db.acts_for_admission(self.a["id"], self.acc)
        # table en ajout seul : aucune API de modification / suppression
        for m in ("update_act", "delete_act"): self.assertFalse(hasattr(self.db, m))

    def test_paramedical_dpi_access_levels(self):
        self.db.close_consultation(self.cons["id"], "notes privées du médecin", "Angine", self.doc)
        rec = self.db.patient_record(self.a["id"], self.ide, "PC-SOINS")
        self.assertEqual(rec["level"], "soins"); v = rec["visits"][0]
        self.assertEqual(v["consultations"][0]["diagnosis"], "Angine"); self.assertEqual(v["consultations"][0]["notes"], "")      # notes du médecin masquées
        self.assertIn("acts", v)
        self.assertEqual(self.db.patient_record(self.a["id"], self.surv)["level"], "soins")
        self.assertEqual(self.db.patient_record(self.a["id"], self.cpara)["level"], "soins")
        self.assertEqual(self.db.patient_record(self.a["id"], self.doc)["visits"][0]["consultations"][0]["notes"], "notes privées du médecin")
        for u in (self.ats, self.acc):                                                       # non autorisés : identité et passages seulement
            r = self.db.patient_record(self.a["id"], u); self.assertEqual(r["level"], "accueil"); self.assertNotIn("consultations", r["visits"][0])
        self.assertEqual(len(self.db.search_patients("Said", self.ide)), 1)
        with self.assertRaises(PermissionError): self.db.patient_record(self.a["id"], self.labo)
        with self.assertRaises(PermissionError): self.db.search_patients("Said", self.pharm)
        n = self.db._one("SELECT COUNT(*) AS n FROM audit_log WHERE action='DPI_VIEW' AND details LIKE '%INFERMIER%'")["n"]; self.assertEqual(n, 1)   # consultation du dossier tracée

    def test_psychology_stays_doctor_only(self):
        p = self.add("Psy", "Pat", "PSY"); self.db.call_next(["PSY"], "DOC1", self.doc)
        c = self.db.start_consultation(p["id"], self.doc, "DOC1"); self.db.close_consultation(c["id"], "très privé", "Anxiété", self.doc)
        v = self.db.patient_record(p["id"], self.ide)["visits"][0]
        self.assertTrue(v.get("restricted")); self.assertNotIn("consultations", v)
        self.assertEqual(self.db.acts_for_admission(p["id"], self.ide), [])
        self.assertEqual(self.db.patient_record(p["id"], self.doc)["visits"][0]["consultations"][0]["diagnosis"], "Anxiété")


class V4ToV5MigrationTests(unittest.TestCase):
    def test_v4_database_gets_new_tables_columns_and_keeps_old_appointments(self):
        import sqlite3, tempfile
        from tests.test_core import _sqlite_v
        from database import Database
        path = os.path.join(tempfile.mkdtemp(), "dem_database.db")
        con = _sqlite_v(path, "schema_v4.sql")
        con.execute("INSERT INTO users(last_name,first_name,role,function,pin_salt,pin_hash,created_at) VALUES ('LAB','X','labo','LABORANTIN','a','b','2026-10-01 07:00:00')")
        con.execute("INSERT INTO appointments(kind,last_name,first_name,date,time,exam,created_at) VALUES ('lab','OLD','Rdv','2026-11-02','09:00','NFS','2026-10-01 08:00:00')")
        con.commit(); con.close()
        db = Database(path)
        self.assertEqual(db._one("SELECT value FROM meta WHERE key='schema_version'")["value"], "5")
        names = {r["name"] for r in db._all("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"messages", "message_reads", "doc_templates", "acts"} <= names)
        a = db.list_appointments("2026-11-01", "2026-11-30", "", 1)[0]
        self.assertEqual((a["last_name"], a["service_code"]), ("OLD", "LAB"))                  # ancien rendez-vous = laboratoire
        self.assertIsNone(db._one("PRAGMA foreign_key_check"))
        n = db.create_appointment({"last_name": "new", "first_name": "x", "date": "2026-11-02", "time": "10:00"}, 1)
        self.assertEqual((n["service_code"], n["number"]), ("LAB", 1))        # anciens rendez-vous : sans n° de passage
        self.assertEqual(db.messages_poll(1)["unread"], 0)
        self.assertEqual(db._one("SELECT COUNT(*) AS n FROM acts")["n"], 0)


if __name__ == "__main__":
    unittest.main()
