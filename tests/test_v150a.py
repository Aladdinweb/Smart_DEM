"""Tests v1.5.0-a : administrateur vérifié par le Hub, statistiques réservées aux responsables, en-tête bilingue FR/AR."""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.test_core import Base, new_db  # noqa: E402

AR_STRUCT = "المؤسسة العمومية للصحة الجوارية السانية - العيادة المتعددة الخدمات عين البيضاء"
EST = {"tutelle_fr": "République Algérienne Démocratique et Populaire - Ministère de la Santé", "tutelle_ar": "الجمهورية الجزائرية الديمقراطية الشعبية - وزارة الصحة",
       "structure_fr": "EPSP ES SENIA - POLYCLINIQUE AADL AIN BEIDA", "structure_ar": AR_STRUCT}


class AdminAndStatsTests(Base):
    def setUp(self):
        super().setUp()
        self.cmed = self.db.create_user("Coord", "Med", "COORDINATEUR DES MÉDECINS", "", "7001")
        self.cpara = self.db.create_user("Coord", "Para", "COORDINATEUR DE PARAMÉDICAL", "", "7002")

    def test_admin_pin_lifecycle_lockout_and_adoption(self):
        db = self.db
        self.assertEqual(db.admin_pin_status(), {"set": False})
        self.assertTrue(db.admin_login("")["ok"])                       # poste local sans PIN : accès historique
        with self.assertRaises(ValueError): db.admin_set_pin("12")
        db.admin_logout(); self.assertTrue(db.admin_set_pin("2468")); self.assertEqual(db.admin_pin_status(), {"set": True})
        with self.assertRaises(PermissionError): db.admin_set_pin("1357")  # PIN existant : session administrateur requise
        for i in range(4): self.assertIn(f"({i + 1}/5)", db.admin_login("0000")["error"])
        self.assertIn("verrouillé", db.admin_login("0000")["error"])
        self.assertIn("verrouillé", db.admin_login("2468")["error"])      # même le bon PIN pendant le blocage
        db.conn.execute("UPDATE meta SET value='2000-01-01 00:00:00' WHERE key='admin_locked_until'"); db.conn.commit()
        self.assertTrue(db.admin_login("2468")["ok"]); self.assertTrue(db.admin_set_pin("1357"))      # session ouverte : changement permis
        db.admin_logout(); self.assertFalse(db.admin_login("2468")["ok"]); self.assertTrue(db.admin_login("1357")["ok"])
        self.assertGreaterEqual(db._one("SELECT COUNT(*) AS n FROM audit_log WHERE action='ADMIN_LOGIN'")["n"], 8)
        db2 = new_db()                                                   # reprise du PIN de l'ancienne configuration (même algorithme)
        from config_manager import _hash
        salt = "ab" * 16
        self.assertTrue(db2.admin_adopt_pin(salt, _hash("4321", salt))); self.assertFalse(db2.admin_adopt_pin("cd" * 16, "x"))
        self.assertTrue(db2.admin_login("4321")["ok"])

    def test_statistics_restricted_to_managers_and_admin(self):
        db, today = self.db, "2026-10-14"
        self.assertEqual(db.stats_report(today, today, self.cmed)["admissions"], 0)       # coordinateurs
        self.assertEqual(db.stats_report(today, today, self.cpara)["admissions"], 0)
        for uid in (self.doc, self.acc, self.labo, self.pharm, self.tech):
            with self.assertRaises(PermissionError): db.stats_report(today, today, uid)
        with self.assertRaises(PermissionError): db.stats_report(today, today)            # anonyme
        db.admin_set_pin("2468"); db.admin_login("2468")                                   # administrateur (session locale)
        self.assertEqual(db.stats_report(today, today)["admissions"], 0)
        db.admin_logout()
        with self.assertRaises(PermissionError): db.stats_report(today, today)
        self.assertEqual(db.stats_report_system(today, today)["admissions"], 0)             # rapport mensuel interne du Hub
        from database import RPC_METHODS
        self.assertNotIn("stats_report_system", RPC_METHODS); self.assertNotIn("admin_adopt_pin", RPC_METHODS); self.assertNotIn("seed_establishment", RPC_METHODS)

    def test_establishment_bilingual_storage_and_revision(self):
        db = self.db
        self.assertEqual(db.get_establishment()["rev"], 0); self.assertEqual(db.messages_poll(self.doc)["estab_rev"], 0)
        self.assertTrue(db.seed_establishment(EST)); self.assertFalse(db.seed_establishment({"structure_fr": "autre"}))
        e = db.get_establishment(); self.assertEqual((e["structure_ar"], e["rev"]), (AR_STRUCT, 1))
        e2 = db.set_establishment({**EST, "structure_ar": "  عيادة جديدة\n"}); self.assertEqual((e2["structure_ar"], e2["rev"]), ("عيادة جديدة", 2))
        self.assertEqual(db.messages_poll(self.doc)["estab_rev"], 2)
        with self.assertRaises(ValueError): db.set_establishment({**EST, "structure_fr": " "})
        with self.assertRaises(ValueError): db.set_establishment({**EST, "structure_ar": "ع" * 201})


try:
    import flask, flask_sock  # noqa: F401
    HAVE_FLASK = True
except ImportError:
    HAVE_FLASK = False


@unittest.skipUnless(HAVE_FLASK, "flask / flask-sock non installés")
class HubAdminBoundaryTests(unittest.TestCase):
    def setUp(self):
        from hub_server import Hub

        class Cfg:
            data = {"lan_token": "secret", "parent": "EPSP X", "structure": "POLY Y"}
            def get(self, k, d=None): return self.data.get(k, d)

        self.db = new_db()
        self.acc = self.db.create_user("A", "B", "accueil", "", "1000"); self.doc = self.db.create_user("D", "E", "medecin", "", "1111")
        self.cm = self.db.create_user("C", "M", "COORDINATEUR DES MÉDECINS", "", "7001")
        self.db.admin_set_pin("2468")
        self.c = Hub(self.db, Cfg()).app.test_client()

    def rpc(self, m, *a, bearer=None, **k):
        h = {"X-DEM-Token": "secret"}
        if bearer: h["Authorization"] = "Bearer " + bearer
        return self.c.post("/rpc", json={"m": m, "a": list(a), "k": k}, headers=h)

    def user_token(self, uid, pin):
        return self.rpc("verify_pin", uid, pin).get_json()["r"]["token"]

    def test_admin_methods_need_hub_verified_admin_token(self):
        for m, a in (("create_user", ("N", "P", "labo", "", "1234")), ("delete_user", (self.acc,)), ("reset_user_pin", (self.acc, "9999")),
                     ("tv_set_screens", ([],)), ("set_establishment", (EST,))):
            self.assertEqual(self.rpc(m, *a).status_code, 401, m)                                       # jeton réseau seul : pas de session
            self.assertEqual(self.rpc(m, *a, bearer=self.user_token(self.doc, "1111")).status_code, 403, m)   # même un médecin connecté
        bad = self.rpc("admin_login", "0000").get_json()["r"]; self.assertFalse(bad["ok"]); self.assertNotIn("token", bad)
        good = self.rpc("admin_login", "2468").get_json()["r"]; self.assertTrue(good["ok"]); tok = good["token"]
        self.assertEqual(self.rpc("create_user", "N", "P", "labo", "", "1234", bearer=tok).status_code, 200)
        self.assertEqual(self.rpc("set_establishment", EST, bearer=tok).status_code, 200)
        self.assertEqual(self.rpc("get_establishment").get_json()["r"]["structure_ar"], AR_STRUCT)     # lecture : jeton réseau seul
        self.assertEqual(self.rpc("create_user", "N2", "P", "labo", "", "1234", bearer=tok[:-3] + "abc").status_code, 401)
        self.assertEqual(self.rpc("admin_set_pin", "5555").status_code, 403)                          # PIN existant : session administrateur requise
        self.assertEqual(self.rpc("admin_set_pin", "5555", bearer=tok).status_code, 200)

    def test_stats_over_the_network(self):
        today = "2026-10-14"
        self.assertEqual(self.rpc("stats_report", today, today).status_code, 401)                      # sans identité
        self.assertEqual(self.rpc("stats_report", today, today, self.doc, bearer=self.user_token(self.doc, "1111")).status_code, 403)
        self.assertEqual(self.rpc("stats_report", today, today, self.cm, bearer=self.user_token(self.cm, "7001")).status_code, 200)
        self.assertEqual(self.rpc("stats_report", today, today, self.acc, bearer=self.user_token(self.doc, "1111")).status_code, 403)   # usurpation
        tok = self.rpc("admin_login", "2468").get_json()["r"]["token"]
        self.assertEqual(self.rpc("stats_report", today, today, bearer=tok).status_code, 200)

    def test_remote_client_uses_admin_bearer_and_expires(self):
        from remote_db import HubError, RemoteDatabase
        rd = RemoteDatabase("x", 1, "secret")
        hub_client = self.c
        def fake_call(method, *a, **k):
            h = {"X-DEM-Token": "secret"}
            use_admin = rd.admin_bearer and (method in __import__("auth").ADMIN_RPC or method in __import__("auth").MANAGER_RPC or method in __import__("auth").ADMIN_AWARE_RPC)
            if use_admin or rd.bearer: h["Authorization"] = "Bearer " + (rd.admin_bearer if use_admin else rd.bearer)
            r = hub_client.post("/rpc", json={"m": method, "a": list(a), "k": k}, headers=h); body = r.get_json()
            if r.status_code != 200: raise PermissionError(body["error"])
            res = body["r"]
            if method == "admin_login" and res.get("ok"): rd.admin_bearer = res.pop("token")
            return res
        rd._call = fake_call
        with self.assertRaises(PermissionError): rd.create_user("N", "P", "labo", "", "1234")
        self.assertFalse(rd.admin_login("0000")["ok"]); self.assertIsNone(rd.admin_bearer)
        self.assertTrue(rd.admin_login("2468")["ok"]); self.assertTrue(rd.admin_bearer)
        self.assertTrue(rd.create_user("N", "P", "labo", "", "1234"))
        rd.logout(); self.assertIsNone(rd.admin_bearer)                       # fin de session = fin de la session administrateur


class BilingualHeaderUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_ui_smoke import HAVE_QT
        if not HAVE_QT:
            raise unittest.SkipTest("PyQt6 non installé")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        import branding
        branding.set_establishment_cache({})

    def test_header_lines_prints_and_dynamic_refresh(self):
        import branding
        from branding import HeaderBar, header_lines
        from printer import appt_ticket_html, ticket_html
        from documents import header_html
        cfg = {"parent": "EPSP X", "structure": "POLY Y"}
        base = [t for t, _s, ar in header_lines(cfg)]
        self.assertEqual(base[0], "République Algérienne Démocratique et Populaire"); self.assertEqual(base[1], "Ministère de la Santé")
        self.assertEqual(base[-1], "EPSP X - POLY Y")                              # sans nom arabe : pas de ligne arabe vide
        self.assertTrue(any(ar for _t, _s, ar in header_lines(cfg)))                 # la tutelle arabe par défaut est affichée
        bar = HeaderBar(cfg, 64); n0 = bar.mid.count()
        branding.set_establishment_cache({**EST, "rev": 1})
        lines = header_lines(cfg)
        self.assertEqual([t for t, _s, _a in lines][-2:], [EST["structure_fr"], AR_STRUCT])         # le nom arabe est juste sous le nom français
        self.assertTrue(lines[-1][2] and not lines[-2][2])
        bar.refresh(); self.assertEqual(bar.mid.count(), n0 + 1)
        texts = [bar.mid.itemAt(i).widget().text() for i in range(bar.mid.count())]; self.assertEqual(texts[-1], AR_STRUCT)
        row = {"service_code": "MG", "created_at": "2026-10-14 10:00:00", "ticket_label": "MG-001", "last_name": "A", "first_name": "B", "triage_level": None}
        html = ticket_html(cfg, row)
        self.assertIn(AR_STRUCT, html); self.assertIn("dir='rtl'", html); self.assertLess(html.index(EST["structure_fr"]), html.index(AR_STRUCT))
        self.assertIn(AR_STRUCT, header_html(cfg)); self.assertIn("وزارة الصحة", header_html(cfg))
        a = appt_ticket_html(cfg, {"id": 1, "date": "2026-10-14", "time": "10:00", "number": 1, "last_name": "X", "first_name": "Y", "service_code": "MG", "exam": "", "qr_text": ""})[0]
        self.assertIn(AR_STRUCT, a)

    def test_window_refreshes_header_when_hub_changes_names(self):
        import branding
        from tests.test_ui_smoke import FakeCfg
        from ui_reception import ReceptionWindow
        db = new_db(); acc = db.create_user("A", "B", "accueil", "", "1000")
        db.seed_establishment(EST); branding.refresh_establishment(db)
        w = ReceptionWindow(FakeCfg(role="accueil"), db); w.set_user([u for u in db.list_users(active_only=True)][0]); w.on_login()
        before = w.header_bar.mid.count()
        db.set_establishment({**EST, "structure_ar": "اسم جديد"})
        w._poll_messages()
        texts = [w.header_bar.mid.itemAt(i).widget().text() for i in range(w.header_bar.mid.count())]
        self.assertEqual(texts[-1], "اسم جديد"); self.assertEqual(w.header_bar.mid.count(), before)
        w._allow_close = True; w.close()

    def test_admin_ok_helper_uses_hub_pin(self):
        from tests.test_ui_smoke import FakeCfg
        from PyQt6.QtWidgets import QInputDialog, QMessageBox
        import ui_login
        db = new_db(); db.admin_set_pin("2468"); cfg = FakeCfg()
        orig_get, orig_warn = QInputDialog.getText, QMessageBox.warning
        QMessageBox.warning = staticmethod(lambda *a, **k: 0)
        try:
            QInputDialog.getText = staticmethod(lambda *a, **k: ("0000", True)); self.assertFalse(ui_login.admin_ok(cfg, None, "t", db))
            QInputDialog.getText = staticmethod(lambda *a, **k: ("2468", True)); self.assertTrue(ui_login.admin_ok(cfg, None, "t", db))
            QInputDialog.getText = staticmethod(lambda *a, **k: ("", False)); self.assertFalse(ui_login.admin_ok(cfg, None, "t", db))
        finally:
            QInputDialog.getText, QMessageBox.warning = orig_get, orig_warn


if __name__ == "__main__":
    unittest.main()
