import os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import Database, parse_age_or_birth
from github_updater import is_newer, parse_semver


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(os.path.join(tempfile.mkdtemp(), "t.db"))
        self.p = parse_age_or_birth("35")

    def add(self, name, svc, g="H", triage=None):
        return self.db.add_admission({"full_name": name, "parsed": self.p, "gender": g, "service_code": svc, "triage": triage}, "PC")

    def test_tickets_per_service_and_reset(self):
        self.assertEqual(self.add("A B", "LAB")["ticket_label"], "LAB-001")
        self.assertEqual(self.add("C D", "LAB")["ticket_label"], "LAB-002")
        self.assertEqual(self.add("E F", "RAD")["ticket_label"], "RAD-001")
        self.db.reset_shift("PC")
        self.assertEqual(self.add("G H", "LAB")["ticket_label"], "LAB-001")

    def test_revisit_info_only(self):
        self.add("Benali Ahmed", "LAB")
        self.assertIsNotNone(self.db.find_revisit("ahmed BENALI", "H", parse_age_or_birth("36"), 24))
        self.assertIsNone(self.db.find_revisit("Benali Ahmed", "F", self.p, 24))
        self.add("Benali Ahmed", "LAB")  # jamais bloquant

    def test_priority_and_call_listener(self):
        self.add("Vert", "MG", triage="VERT"); self.add("Rouge", "MG", triage="ROUGE")
        seen = []
        self.db.call_listeners.append(lambda row, rc, st: seen.append((row["ticket_label"], rc)))
        self.assertEqual(self.db.call_next(["MG"], "DOC")["ticket_label"], "MG-002")
        self.assertEqual(seen, [("MG-002", False)])

    def test_edit_keeps_ticket(self):
        a = self.add("Erreur", "LAB")
        u = self.db.update_admission(a["id"], {"full_name": "Correct", "parsed": self.p, "gender": "H", "service_code": "RAD"}, "PC")
        self.assertEqual(u["ticket_label"], "LAB-001")


class SemVerTests(unittest.TestCase):
    def test_compare(self):
        self.assertTrue(is_newer("v1.0.1", "1.0.0"))
        self.assertTrue(is_newer("v1.10.0", "1.9.9"))
        self.assertFalse(is_newer("v1.0.0", "1.0.0"))
        self.assertFalse(is_newer("v2.0.0-rc.1", "2.0.0"))
        self.assertFalse(is_newer("n'importe quoi", "1.0.0"))
        self.assertIsNone(parse_semver("1.0"))


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

        db = Database(os.path.join(tempfile.mkdtemp(), "h.db")); hub = Hub(db, Cfg()); c = hub.app.test_client()
        body = {"m": "current_shift", "a": ["PC"], "k": {}}
        self.assertEqual(c.post("/rpc", json=body).status_code, 403)
        self.assertEqual(c.post("/rpc", json=body, headers={"X-DEM-Token": "secret"}).status_code, 200)
        self.assertEqual(c.post("/rpc", json={"m": "backup"}, headers={"X-DEM-Token": "secret"}).status_code, 400)
        self.assertEqual(c.get("/api/ping").get_json()["name"], "EPSP X — POLY Y")
        hub.test_call(); self.assertEqual(hub.recent[0]["ticket"], "TEST-000")
        self.assertIn("ws/tv", c.get("/tv").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
