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


USERS = (("Martin", "MÉDECIN", ["MG"]), ("Dent", "MÉDECIN", ["DENT"]), ("Duval", "MÉDECIN", ["MG"]), ("Radi", "MANIPULATEUR", []),
         ("Pharma", "PHARMACIEN", []), ("Acc", "AGENT DE BUREAU", []), ("Labo", "LABORANTIN", []), ("Soin", "INFERMIER", []),
         ("Cmed", "COORDINATEUR DES MÉDECINS", []), ("Cpara", "COORDINATEUR DE PARAMÉDICAL", []), ("Urg", "RESPONSABLE URGENCES", []))


@unittest.skipUnless(HAVE_QT, "PyQt6 non installé")
class UiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        from database import Database
        cls.app = QApplication.instance() or QApplication([])
        cls.db = Database(os.path.join(TMP, "ui.db"))
        for i, (last, fn, svc) in enumerate(USERS):
            cls.db.create_user(last, "Test", fn, "", f"{1000 + i}", svc)

    def user(self, last):
        return [u for u in self.db.list_users(active_only=True) if u["last_name"] == last.upper()][0]

    def mk(self, cls, last, **cfg):
        w = cls(FakeCfg(**cfg), self.db); w.set_user(self.user(last)); w.on_login(); return w

    def test_branding_logo_import_same_size_and_dynamic_header(self):
        from PyQt6.QtGui import QColor, QImage
        import branding
        self.assertIsNone(branding.ministry_pixmap(64))
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
        acc, doc = self.user("Acc")["id"], self.user("Martin")["id"]
        a = self.db.add_admission({"last_name": "Said", "first_name": "Omar", "parsed": {"birth_date": None, "birth_year": 1985}, "gender": "H",
                                   "service_code": "MG", "ident": "123456", "user_id": acc}, "ACC")
        self.db.call_next(["MG"], "D", doc); cons = self.db.start_consultation(a["id"], doc, "D")
        rx = self.db.create_prescription(cons["id"], [{"drug": "Paracétamol 500 mg cp", "dosage": "1 cp x 3/j", "duration": "5 jours"}], "", doc)
        html, res = build_prescription(cfg, rx, self.db.get(a["id"]), self.db.get_user(doc))
        self.assertNotIn("République", html)
        ok, msg = print_document(cfg, html, res, "a4", "ordonnance_test", template_kind="ordonnance"); self.assertTrue(ok, msg)
        self.db.close_consultation(cons["id"], "", "", doc)

    def test_banner_auto_hides_and_signature_editor(self):
        from PIL import Image, ImageDraw
        from ui_reception import ReceptionWindow
        from ui_sigeditor import SignatureEditor
        w = self.mk(ReceptionWindow, "Acc")
        w.show_banner("Compteurs remis à zéro"); self.assertTrue(w._banner_timer.isActive()); self.assertLessEqual(w._banner_timer.interval(), 6000)
        w._allow_close = True; w.close()
        im = Image.new("RGB", (300, 150), (210, 210, 210)); ImageDraw.Draw(im).line((30, 40, 260, 110), fill=(0, 0, 90), width=7)
        b = io.BytesIO(); im.save(b, "PNG")
        ed = SignatureEditor("Griffe"); ed.raw = b.getvalue(); ed.render(); self.assertTrue(ed.result_png)

    def test_user_folders_and_form_with_official_functions(self):
        import userdata
        from ui_login import UserForm
        from ui_reception import ReceptionWindow
        w = self.mk(ReceptionWindow, "Acc"); w._allow_close = True; w.close()
        d = userdata.user_dir(self.user("Acc"))
        self.assertTrue(os.path.exists(os.path.join(d, "profile.json")) and "connexion" in open(os.path.join(d, "activity.log"), encoding="utf-8").read())
        f = UserForm(); self.assertEqual(f.function(), "AGENT DE BUREAU")
        f.func.setCurrentIndex(f.func.findData("PÉDIATRE")); self.assertTrue(f.services() == ["PED"])
        f.func.setCurrentIndex(f.func.findData("INFERMIER")); self.assertEqual((f.services(), f.space.text()), ([], "Soins & Triage"))
        self.assertEqual(sum(1 for i in range(f.func.count()) if f.func.itemData(i)), 22)         # les 22 fonctions officielles

    def test_all_spaces_and_end_to_end_flow_with_soins_handover_and_coordinators(self):
        from PyQt6.QtCore import Qt
        import main
        from ui_coord import CoordWindow
        from ui_doctor import DoctorWindow
        from ui_dpi import PatientSearchDialog
        from ui_lab import LabWindow
        from ui_pharmacy import PharmacyWindow
        from ui_radio import RadioWindow
        from ui_reception import ReceptionWindow
        from ui_soins import SoinsWindow
        self.assertEqual(len(main.ROLES), 8)
        for r in main.ROLES:
            self.assertTrue(main.window_class(r).__name__.endswith("Window"))
        rw = self.mk(ReceptionWindow, "Acc"); rw.last_edit.setText("Said"); rw.first_edit.setText("Omar"); rw.age_edit.setText("40")
        rw.btn_h.setChecked(True)
        soins_btn = [b for b in rw.service_group.buttons() if b.property("code") == "SOINS"][0]; soins_btn.setChecked(True); rw.on_service_changed(); rw.submit()
        self.assertEqual(len(self.db.queue(["SOINS"])), 1)
        sw = self.mk(SoinsWindow, "Soin"); sw.call_next(); self.assertIsNotNone(sw.current)
        sw.sys.setText("120"); sw.dia.setText("80"); sw.glyc.setText("1,1"); sw.temp.setText("37,2"); sw.autosave(); sw.save_vitals()
        self.assertEqual(len(self.db.vitals_for_admission(sw.current["id"], sw.user["id"])), 1)
        sw.dest.setCurrentIndex(sw.dest.findData("MG")); sw.orient(); self.assertIsNone(sw.current)
        w = self.mk(DoctorWindow, "Martin", station_name="DOC-TEST")
        self.assertEqual(w.services, ["MG"]); w.call_next(); self.assertIsNotNone(w.consult)
        self.assertIn("TA 120", w.cur_vitals.text())                                              # constantes du soignant visibles du médecin
        w.diag.setText("Angine"); w.notes.setPlainText("à revoir"); w.autosave()                    # brouillon enregistré
        self.assertEqual(self.db.get_draft(w.current["id"], "consult", w.user["id"])["diag"], "Angine")
        w.drug.setText("Paracétamol 500 mg cp"); w.dose.setText("1 cp x 3/j"); w.dur.setText("5 jours"); w.add_item(); w.print_rx(); self.assertIsNotNone(w.rx)
        w.send_pharmacy(); w.r_region.setCurrentText("Thorax"); w.r_instr.setText("Face et profil"); w.send_radio()
        w.lab_list.item(0).setCheckState(Qt.CheckState.Checked); w.send_lab()
        self.assertEqual((len(self.db.radio_queue(self.user("Radi")["id"])), len(self.db.lab_queue(self.user("Labo")["id"]))), (1, 1))
        # relève de garde : le patient est réservé, le confrère le reprend avec le brouillon
        adm = w.current["id"]; self.db.handover_start(adm, "Voir l'ECG", w.user["id"])
        w2 = self.mk(DoctorWindow, "Duval"); w2.refresh(); self.assertIn("(1)", w2.btn_hand.text())
        self.db.take_over(adm, w2.user["id"]); w2.set_current(self.db.get(adm)); self.assertEqual(w2.diag.text(), "Angine")
        w2.close_consult(); self.assertIsNone(w2.current)
        dent = self.mk(DoctorWindow, "Dent"); self.assertEqual((dent.services, dent.r_type.currentText()), (["DENT"], "Radio panoramique dentaire"))
        urg = self.mk(DoctorWindow, "Urg"); self.assertTrue(urg.user["function"] == "RESPONSABLE URGENCES")
        radio = self.mk(RadioWindow, "Radi"); radio.call_next(); self.assertIsNotNone(radio.current); self.assertIn("Face et profil", radio._detail(radio.current))
        radio.db.add_result("radio", radio.current["id"], None, None, None, "Pas de fracture.", radio.user["id"]); radio.validate("DONE")
        lab = self.mk(LabWindow, "Labo"); lab.t_last.setText("Ali"); lab.t_first.setText("Sam"); lab.t_age.setText("30")
        self.assertTrue(lab.issue()["ticket_label"].startswith("LAB")); lab.refresh_appts()
        ph = self.mk(PharmacyWindow, "Pharma"); ph.refresh(); self.assertEqual(ph.queue.rowCount(), 1)
        for last in ("Cmed", "Cpara"):
            cw = self.mk(CoordWindow, last); cw.refresh(); self.assertGreaterEqual(cw.over.rowCount(), 1); cw._allow_close = True; cw.close()
        dlg = PatientSearchDialog(self.db, self.user("Martin"), FakeCfg()); dlg.q.setText("said"); dlg.search()
        self.assertEqual(dlg.table.rowCount(), 1); dlg.table.selectRow(0); dlg._reload(); self.assertGreaterEqual(dlg.tree.topLevelItemCount(), 1)
        for x in (sw, w, w2, dent, urg, radio, lab, ph, rw):
            x._allow_close = True; x.close()


if __name__ == "__main__":
    unittest.main()
