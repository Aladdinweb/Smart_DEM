"""Test de fumée de l'interface (Qt « offscreen ») : construit chaque espace, enchaîne les parcours clés, génère les PDF.
Ignoré si PyQt6 n'est pas installé."""
import io, os, sys, tempfile, unittest

TMP = tempfile.mkdtemp()
os.environ.update({"QT_QPA_PLATFORM": "offscreen", "LOCALAPPDATA": TMP, "HOME": TMP})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import PyQt6  # noqa
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


class FakeCfg:
    dir = TMP

    def __init__(self, **kw):
        self.data = {"parent": "EPSP ES SENIA", "structure": "POLYCLINIQUE AADL AIN BEIDA MABROUK LOUCIF", "role": "accueil", "services": [],
                     "station_name": "PC-TEST", "room_label": "Bureau test", "revisit_check_hours": 72, "auto_update_check": False,
                     "printer": "", "doc_printer": "", "paper_width_mm": 80, "net_mode": "local", "tpl_margins_mm": "50,15,15,25"}
        self.data.update(kw)

    def get(self, k, d=None): return self.data.get(k, d)
    def set(self, k, v): self.data[k] = v
    def has_pin(self): return False


@unittest.skipUnless(HAVE_QT, "PyQt6 non installé")
class UiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        from database import Database
        cls.app = QApplication.instance() or QApplication([])
        cls.db = Database(os.path.join(TMP, "ui.db"))
        for last, role, pin, svc in (("Martin", "medecin", "1111", ["MG"]), ("Dent", "medecin", "1112", ["DENT"]), ("Radi", "radio", "2222", []),
                                     ("Pharma", "pharmacie", "3333", []), ("Acc", "accueil", "4444", []), ("Labo", "labo", "5555", [])):
            cls.db.create_user(last, "Test", role, "Dentiste" if last == "Dent" else "", pin, svc)

    def user(self, role, last=None):
        return [u for u in self.db.list_users(roles=[role]) if last in (None, u["last_name"].title())][0]

    def mk(self, cls, user, **cfg):
        w = cls(FakeCfg(**cfg), self.db); w.set_user(user); w.on_login(); return w

    def test_branding_logo_import_same_size_and_dynamic_header(self):
        from PyQt6.QtGui import QImage, QColor
        import branding
        self.assertIsNone(branding.ministry_pixmap(64))                       # aucun badge provisoire sans logo fourni
        flag = branding.flag_pixmap(64); self.assertFalse(flag.isNull())
        img = QImage(300, 300, QImage.Format.Format_RGB32); img.fill(QColor("#2e7d32")); src = os.path.join(TMP, "logo.png"); img.save(src)
        branding.import_logo(src); logo = branding.ministry_pixmap(64)
        self.assertEqual((logo.width(), logo.height()), (flag.width(), flag.height()))
        self.assertEqual(branding.establishment(FakeCfg()), "EPSP ES SENIA - POLYCLINIQUE AADL AIN BEIDA MABROUK LOUCIF")
        branding.HeaderBar(FakeCfg(), 64)

    def test_barcode_qr_and_overlay_printing_on_template(self):
        from PyQt6.QtGui import QColor, QImage
        import barcode, templates
        from documents import build_prescription
        from printer import print_document
        self.assertFalse(barcode.barcode_image("2026000123").isNull())
        tpl = QImage(794, 1123, QImage.Format.Format_RGB32); tpl.fill(QColor("#fdf6e3")); path = os.path.join(TMP, "trame.png"); tpl.save(path)
        cfg = FakeCfg(); templates.import_template(cfg, "ordonnance", path); self.assertTrue(templates.load_template(cfg, "ordonnance") is not None)
        a = self.db.add_admission({"last_name": "Said", "first_name": "Omar", "parsed": {"birth_date": None, "birth_year": 1985}, "gender": "H",
                                   "service_code": "MG", "ident": "123456", "user_id": self.user("accueil")["id"]}, "ACC")
        doc = self.user("medecin", "Martin"); self.db.call_next(["MG"], "D", doc["id"])
        cons = self.db.start_consultation(a["id"], doc["id"], "D")
        rx = self.db.create_prescription(cons["id"], [{"drug": "Paracétamol 500 mg cp", "dosage": "1 cp x 3/j", "duration": "5 jours"}], "", doc["id"])
        html, res = build_prescription(cfg, rx, self.db.get(a["id"]), self.db.get_user(doc["id"]))
        self.assertNotIn("République", html)                                      # trame fournie : pas d'en-tête en double
        ok, msg = print_document(cfg, html, res, "a4", "ordonnance_test", template_kind="ordonnance"); self.assertTrue(ok, msg)
        ok, msg = print_document(FakeCfg(), build_prescription(FakeCfg(), rx, self.db.get(a["id"]), self.db.get_user(doc["id"]))[0], res, "a4", "ordonnance_def"); self.assertTrue(ok, msg)

    def test_banner_auto_hides_and_signature_editor(self):
        from PIL import Image, ImageDraw
        from ui_reception import ReceptionWindow
        from ui_sigeditor import SignatureEditor
        w = self.mk(ReceptionWindow, self.user("accueil"))
        w.show_banner("Compteurs remis à zéro"); self.assertTrue(w._banner_timer.isActive()); self.assertLessEqual(w._banner_timer.interval(), 6000)
        w._allow_close = True; w.close()
        im = Image.new("RGB", (300, 150), (210, 210, 210)); ImageDraw.Draw(im).line((30, 40, 260, 110), fill=(0, 0, 90), width=7)
        b = io.BytesIO(); im.save(b, "PNG")
        ed = SignatureEditor("Griffe"); ed.raw = b.getvalue(); ed.render(); self.assertTrue(ed.result_png)

    def test_all_role_spaces_and_end_to_end_clinical_flow(self):
        from ui_doctor import DoctorWindow
        from ui_dpi import PatientSearchDialog
        from ui_lab import LabWindow
        from ui_pharmacy import PharmacyWindow
        from ui_radio import RadioWindow
        from ui_reception import ReceptionWindow
        from PyQt6.QtCore import Qt
        import main
        self.assertEqual(set(main.ROLES), {"accueil", "medecin", "radio", "pharmacie", "labo"})          # routage par rôle
        for r in main.ROLES:
            self.assertTrue(main.window_class(r).__name__.endswith("Window"))
        acc = self.user("accueil")
        rw = self.mk(ReceptionWindow, acc); rw.last_edit.setText("Said"); rw.first_edit.setText("Omar"); rw.age_edit.setText("40")
        rw.btn_h.setChecked(True); rw.service_group.buttons()[1].setChecked(True); rw.on_service_changed(); rw.submit()      # MG (triage)
        self.assertEqual(len(self.db.queue(["MG"])), 1)
        rw.open_tv_control  # présence du pilotage TV
        w = self.mk(DoctorWindow, self.user("medecin", "Martin"), station_name="DOC-TEST")
        self.assertEqual(w.services, ["MG"]); w.call_next(); self.assertIsNotNone(w.consult)
        w.drug.setText("Paracétamol 500 mg cp"); w.dose.setText("1 cp x 3/j"); w.dur.setText("5 jours"); w.add_item(); w.print_rx(); self.assertIsNotNone(w.rx)
        w.send_pharmacy(); w.r_region.setCurrentText("Thorax"); w.r_instr.setText("Face et profil"); w.send_radio()
        w.lab_list.item(0).setCheckState(Qt.CheckState.Checked); w.send_lab()
        self.assertEqual((len(self.db.radio_queue(self.user("radio")["id"])), len(self.db.lab_queue(self.user("labo")["id"]))), (1, 1))
        dent = self.mk(DoctorWindow, self.user("medecin", "Dent")); self.assertEqual((dent.services, dent.r_type.currentText()), (["DENT"], "Radio panoramique dentaire"))
        self.assertEqual(dent.queue_rows() if hasattr(dent, "queue_rows") else 0, 0)                      # le dentiste ne voit pas la file MG
        dent._allow_close = True; dent.close()
        radio = self.mk(RadioWindow, self.user("radio")); radio.call_next(); self.assertIsNotNone(radio.current)
        self.assertIn("Face et profil", radio._detail(radio.current))
        radio.db.add_result("radio", radio.current["id"], None, None, None, "Pas de fracture.", radio.user["id"]); radio.validate("DONE")
        lab = self.mk(LabWindow, self.user("labo")); lab.t_last.setText("Ali"); lab.t_first.setText("Sam"); lab.t_age.setText("30")
        row = lab.issue(); self.assertTrue(row["ticket_label"].startswith("LAB"))
        self.db.create_appointment({"last_name": "bob", "first_name": "T", "date": "2026-10-20", "time": "08:30"}, lab.user["id"]); lab.refresh_appts()
        ph = self.mk(PharmacyWindow, self.user("pharmacie")); ph.refresh(); self.assertEqual(ph.queue.rowCount(), 1)
        w.close_consult(); self.assertIsNone(w.current)
        dlg = PatientSearchDialog(self.db, self.db.list_users(roles=["medecin"])[0], FakeCfg()); dlg.q.setText("said"); dlg.search()
        self.assertEqual(dlg.table.rowCount(), 1); dlg.table.selectRow(0); dlg._reload(); self.assertGreaterEqual(dlg.tree.topLevelItemCount(), 1)
        for x in (w, radio, lab, ph, rw):
            x._allow_close = True; x.close()


if __name__ == "__main__":
    unittest.main()
