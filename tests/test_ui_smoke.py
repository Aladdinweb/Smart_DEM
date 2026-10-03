"""Test de fumée de l'interface (Qt « offscreen ») : crée les 4 postes, enchaîne un parcours complet et génère les PDF.
Ignoré si PyQt6 n'est pas installé."""
import os, sys, tempfile, unittest

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
        self.data = {"parent": "EPSP TEST", "structure": "POLYCLINIQUE TEST", "role": "accueil", "services": [],
                     "station_name": "PC-TEST", "revisit_check_hours": 72, "auto_update_check": False,
                     "printer": "", "doc_printer": "", "paper_width_mm": 80, "net_mode": "local"}
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
        for last, role, pin in (("Martin", "medecin", "1111"), ("Radi", "radio", "2222"), ("Pharma", "pharmacie", "3333"), ("Acc", "accueil", "4444")):
            cls.db.create_user(last, "Test", role, "Généraliste" if role == "medecin" else "", pin)

    def user(self, role):
        return self.db.list_users(roles=[role])[0]

    def test_branding_same_size_circles(self):
        from branding import flag_pixmap, ministry_pixmap
        a, b = flag_pixmap(64), ministry_pixmap(64)
        self.assertFalse(a.isNull() or b.isNull())
        self.assertEqual((a.width(), a.height()), (b.width(), b.height()))

    def test_ticket_prints_silently_to_pdf(self):
        from printer import print_ticket
        row = {"service_code": "LAB", "ticket_label": "LAB-001", "full_name": "TEST Patient", "last_name": "TEST", "first_name": "Patient",
               "triage_level": None, "created_at": "2026-10-03 10:00:00"}
        ok, msg = print_ticket(FakeCfg(), row)
        self.assertTrue(ok, msg)
        self.assertTrue(any(f.endswith(".pdf") for f in os.listdir(os.path.join(TMP, "Smart_DEM", "tickets")))
                        if os.name == "nt" else any(f.endswith(".pdf") for f in os.listdir(os.path.join(TMP, ".local", "share", "Smart_DEM", "tickets"))))

    def test_windows_and_full_doctor_flow(self):
        from database import parse_age_or_birth
        from ui_doctor import DoctorWindow
        from ui_pharmacy import PharmacyWindow
        from ui_radio import RadioWindow
        from ui_reception import ReceptionWindow
        db = self.db
        for cls, role, extra in ((ReceptionWindow, "accueil", {}), (RadioWindow, "radio", {"role": "radio"}),
                                 (PharmacyWindow, "pharmacie", {"role": "pharmacie"})):
            w = cls(FakeCfg(**extra), db); w.user = self.user(role); w.on_login(); w.refresh(); w._allow_close = True; w.close()
        db.add_admission({"last_name": "Said", "first_name": "Omar", "parsed": parse_age_or_birth("40"), "gender": "H",
                          "service_code": "MG", "triage": "ROUGE"}, "ACC")
        w = DoctorWindow(FakeCfg(role="medecin", services=["MG"], station_name="DOC-TEST"), db)
        w.user = self.user("medecin"); w.on_login(); w.refresh()
        w.call_next()
        self.assertIsNotNone(w.consult)
        w.drug.setText("Paracétamol 500 mg cp"); w.dose.setText("1 cp x 3/j"); w.dur.setText("5 jours"); w.add_item()
        w.print_rx(); self.assertIsNotNone(w.rx)
        w.send_pharmacy(); self.assertEqual(len(db.pharmacy_queue()), 1)
        w.r_region.setCurrentText("Thorax"); w.send_radio(); self.assertEqual(len(db.radio_queue()), 1)
        w.lab_list.item(0).setCheckState(__import__("PyQt6.QtCore", fromlist=["Qt"]).Qt.CheckState.Checked); w.print_lab()
        w.close_consult(); self.assertIsNone(w.current)
        w._allow_close = True; w.close()
        rw = RadioWindow(FakeCfg(role="radio", station_name="RADIO-TEST"), db)
        rw.user = self.user("radio"); rw.on_login(); rw.call_next(); self.assertIsNotNone(rw.current)
        rw.validate("DONE"); rw._allow_close = True; rw.close()


if __name__ == "__main__":
    unittest.main()
