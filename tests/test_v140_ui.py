"""Tests d'interface v1.4.0 (Qt « offscreen ») : messagerie, rendez-vous + QR, modèles de documents, DPI paramédical, 4:3 / 16:9."""
import base64, os, unittest
from datetime import date

from tests.test_ui_smoke import HAVE_QT, TMP, FakeCfg


@unittest.skipUnless(HAVE_QT, "PyQt6 non installé")
class V140Ui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        from database import Database
        cls.app = QApplication.instance() or QApplication([])
        cls.db = Database(os.path.join(TMP, "ui140.db"))
        for i, (last, fn, svc) in enumerate((("Martin", "MÉDECIN", ["MG"]), ("Acc", "AGENT DE BUREAU", []), ("Soin", "INFERMIER", []), ("Ats", "ATS", []),
                                             ("Cmed", "COORDINATEUR DES MÉDECINS", []), ("Cpara", "COORDINATEUR DE PARAMÉDICAL", []), ("Radi", "MANIPULATEUR", []))):
            cls.db.create_user(last, "Test", fn, "", f"{2000 + i}", svc)

    def user(self, last):
        return [u for u in self.db.list_users(active_only=True) if u["last_name"] == last.upper()][0]

    def mk(self, cls, last, **cfg):
        w = cls(FakeCfg(**cfg), self.db); w.set_user(self.user(last)); w.on_login(); return w

    def test_message_popup_badge_and_dialogs_never_on_tv(self):
        from ui_doctor import DoctorWindow
        from ui_messages import ComposeDialog, MessagePopup, MessagesDialog
        w = self.mk(DoctorWindow, "Martin", role="medecin", services=["MG"])
        tv = []; self.db.tv_listeners.append(tv.append)
        self.db.send_message({"to_user_ids": [self.user("Martin")["id"]], "reason": "Réunion 14h", "body": "Salle A"}, self.user("Cmed")["id"], "PC-COORD")
        w._poll_messages()
        self.assertIn("(1)", w.btn_msg.text()); self.assertTrue(w._popups and isinstance(w._popups[0], MessagePopup))   # convocation : fenêtre sur le poste
        pop = w._popups[0]; self.assertIn("Réunion 14h", pop.findChildren(__import__("PyQt6.QtWidgets", fromlist=["QLabel"]).QLabel)[1].text())
        pop._ack(); w._poll_messages(); self.assertNotIn("(", w.btn_msg.text())
        dlg = MessagesDialog(self.db, self.user("Martin"), "PC", w)
        self.assertEqual(dlg.t_in.rowCount(), 1); dlg.t_in.selectRow(0); self.assertIn("Réunion 14h", dlg.detail.toPlainText()); self.assertIn("Service émetteur", dlg.detail.toPlainText())
        agent_compose = ComposeDialog(self.db, self.user("Martin"), w); self.assertIsNotNone(agent_compose.combo); self.assertIsNone(agent_compose.lst)
        coord_compose = ComposeDialog(self.db, self.user("Cmed"), w); self.assertIsNotNone(coord_compose.lst); self.assertGreater(coord_compose.lst.count(), 3)
        self.assertEqual(tv, [])

    def test_appointments_panel_qr_checkin_and_queue_insertion(self):
        from ui_appointments import AppointmentsPanel, allowed_services
        acc = self.user("Acc")
        self.assertNotIn("URG", allowed_services(acc)); self.assertIn("DENT", allowed_services(acc)); self.assertEqual(allowed_services(self.user("Radi")), ["RAD"])
        p = AppointmentsPanel(self.db, FakeCfg(role="accueil"), None); p.set_user(acc)
        a = self.db.create_appointment({"last_name": "Qr", "first_name": "Test", "birth_year": 1990, "gender": "F", "date": date.today().isoformat(), "time": "09:15",
                                        "service_code": "DENT"}, acc["id"])
        p.refresh(); self.assertEqual(p.all_table.rowCount(), 1); self.assertEqual(p.day_table.rowCount(), 1)
        got = []; p.changed.connect(lambda: got.append(1))
        p.scan.setText(a["qr_text"]); p._scan()
        self.assertEqual(got, [1]); self.assertIn("inséré dans la file", p.msg.text())
        self.assertEqual([x["last_name"] for x in self.db.queue(["DENT"])], ["QR"])
        p.scan.setText(a["qr_text"]); p._scan(); self.assertIn("déjà enregistré", p.msg.text())            # deuxième scan refusé
        p.scan.setText("SDEMR1" + "a" * 24); p._scan(); self.assertIn("signature", p.msg.text())
        from printer import appt_ticket_html
        html, res = appt_ticket_html(FakeCfg(), a); self.assertIn("TICKET DE RENDEZ-VOUS", html); self.assertIn("qr", res); self.assertIn("N° de passage", html)
        from printer import print_appt_ticket
        ok, m = print_appt_ticket(FakeCfg(), a); self.assertTrue(ok, m)

    def test_templates_documents_and_dpi_paramedical(self):
        from ui_dpi import PatientSearchDialog
        from ui_templates import DocumentDialog, TemplatesDialog
        doc = self.user("Martin")
        self.db.import_doc_template("bonne_sante", "b.txt", base64.b64encode("BON POUR {{nom}} {{prenom}} par {{medecin}}".encode()).decode(), doc["id"])
        t = TemplatesDialog(self.db, doc); self.assertEqual(t.table.rowCount(), 1); self.assertGreaterEqual(t.kind.count(), 6)
        adm = self.db.add_admission({"last_name": "Said", "first_name": "Omar", "gender": "H", "service_code": "MG", "parsed": {"birth_date": None, "birth_year": 1980},
                                     "ident": "", "triage": "VERT", "user_id": self.user("Acc")["id"]}, "PC")
        d = DocumentDialog(self.db, FakeCfg(), doc, self.db.get(adm["id"]), "MG")
        i = [d.combo.itemText(k) for k in range(d.combo.count())].index(next(x for x in [d.combo.itemText(k) for k in range(d.combo.count())] if "bonne santé —" in x and "b.txt" in x))
        d.combo.setCurrentIndex(i); self.assertIn("BON POUR SAID Omar par Dr Martin Test".replace("Martin Test", "MARTIN Test"), d.text.toPlainText())
        d.print_it(); self.assertIn("🖨", d.msg.text())
        self.assertEqual(self.db.acts_for_admission(adm["id"], doc["id"])[-1]["label"], "Document établi : Certificat de bonne santé")
        self.db.call_next(["MG"], "R1", doc["id"]); c = self.db.start_consultation(adm["id"], doc["id"], "R1"); self.db.close_consultation(c["id"], "secret", "Rhume", doc["id"])
        for last, level in (("Soin", "soins"), ("Cpara", "soins"), ("Ats", "accueil")):
            u = self.user(last); dpi = PatientSearchDialog(self.db, u, FakeCfg(), None)
            dpi.q.setText("said"); dpi.search(); dpi.table.selectRow(0); dpi._reload()
            text = []
            def walk(it):
                text.append(it.text(0) + " " + it.text(1)); [walk(it.child(k)) for k in range(it.childCount())]
            [walk(dpi.tree.topLevelItem(k)) for k in range(dpi.tree.topLevelItemCount())]
            blob = "\n".join(text)
            if level == "soins":
                self.assertIn("Rhume", blob); self.assertNotIn("secret", blob); self.assertIn("Actes tracés", blob); self.assertIn("Paramédical".lower(), dpi.hint.text().lower())
            else:
                self.assertNotIn("Rhume", blob); self.assertIn("identité", dpi.hint.text())

    def test_soins_act_button_and_adaptive_profiles(self):
        from ui_layout import profile
        from ui_soins import SoinsWindow
        import ui_common, ui_layout
        w = self.mk(SoinsWindow, "Soin", role="soins")
        adm = self.db.add_admission({"last_name": "Act", "first_name": "Ion", "gender": "H", "service_code": "SOINS", "parsed": {"birth_date": None, "birth_year": 1975},
                                     "ident": "", "user_id": self.user("Acc")["id"]}, "PC")
        w.current = self.db.get(adm["id"]); w.act.setCurrentText("Pansement"); w.act_note.setText("main"); w.save_act()
        self.assertEqual([a["label"] for a in self.db.acts_for_admission(adm["id"], self.user("Soin")["id"])], ["Pansement"])
        self.assertTrue(profile(FakeCfg(screen_format="4:3"))["two_rows"]); self.assertEqual(profile(FakeCfg(screen_format="16:9"))["name"], "16:9")
        self.assertEqual(ui_layout.ratio_name(1024 / 768), "4:3"); self.assertEqual(ui_layout.ratio_name(1280 / 1024), "4:3"); self.assertEqual(ui_layout.ratio_name(1920 / 1080), "16:9")
        from styles import stylesheet
        self.assertNotEqual(stylesheet("dark", True), stylesheet("dark", False)); self.assertNotIn("${", stylesheet("dark", True))
        w.resize(1024, 768); w.show(); self.app.processEvents(); self.assertTrue(w._two)                               # 1024 px : en-têtes sur deux lignes
        w.close()


if __name__ == "__main__":
    unittest.main()
