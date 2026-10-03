"""Hub LAN (Flask + WebSocket natif) : RPC vers la base du poste Hub, écran TV (/tv), diffusion des appels.
Fonctionne SANS internet : aucune ressource externe (le navigateur de la TV n'a besoin que du LAN)."""
import hmac, json, threading, time

from flask import Flask, Response, jsonify, request
from flask_sock import Sock
from werkzeug.serving import make_server

from data_structures import SERVICE_BY_CODE
from database import RPC_METHODS
from tv_page import TV_HTML
from version import __version__

CURRENT = None   # instance active (pour le bouton « Tester l'écran TV »)


class Hub:
    def __init__(self, db, cfg):
        global CURRENT
        self.db, self.cfg = db, cfg
        self.tv_clients, self.recent, self.lock, self.server = set(), [], threading.Lock(), None
        self.app = Flask(__name__)
        self.sock = Sock(self.app)
        self._routes()
        db.call_listeners.append(self.on_call)
        CURRENT = self

    # --- diffusion vers les écrans TV : numéro + service + salle UNIQUEMENT (jamais de nom de patient) ---
    def on_call(self, row, is_recall, station):
        svc = SERVICE_BY_CODE.get(row["service_code"], {})
        ev = {"type": "call", "ticket": row["ticket_label"], "icon": svc.get("icon", ""),
              "service": svc.get("name", ""), "room": station, "recall": bool(is_recall), "at": time.strftime("%H:%M")}
        with self.lock:
            self.recent.insert(0, ev); del self.recent[8:]
        self._broadcast(ev)

    def _broadcast(self, ev):
        msg = json.dumps(ev, ensure_ascii=False)
        with self.lock:
            for ws in list(self.tv_clients):
                try:
                    ws.send(msg)
                except Exception:
                    self.tv_clients.discard(ws)

    def test_call(self):
        self.on_call({"ticket_label": "TEST-000", "service_code": "LAB"}, False, "Test écran TV")

    def _authorized(self):
        token = self.cfg.get("lan_token", "")
        return bool(token) and hmac.compare_digest(request.headers.get("X-DEM-Token", ""), token)

    def _routes(self):
        app, cfg = self.app, self.cfg

        @app.get("/api/ping")
        def ping():
            return jsonify({"ok": True, "version": __version__,
                            "name": f"{cfg.get('parent', '')} — {cfg.get('structure', '')}"})

        @app.post("/rpc")
        def rpc():
            if not self._authorized():
                return jsonify({"error": "forbidden"}), 403
            d = request.get_json(force=True, silent=True) or {}
            m = d.get("m")
            if m not in RPC_METHODS:
                return jsonify({"error": "méthode inconnue"}), 400
            try:
                return jsonify({"r": getattr(self.db, m)(*d.get("a", []), **d.get("k", {}))})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.get("/tv")
        def tv():
            return Response(TV_HTML, mimetype="text/html; charset=utf-8")

        @self.sock.route("/ws/tv")
        def ws_tv(ws):
            with self.lock:
                self.tv_clients.add(ws)
                ws.send(json.dumps({"type": "snapshot", "recent": self.recent}, ensure_ascii=False))
            try:
                while True:
                    if ws.receive(timeout=25) is None:      # silence : battement de coeur
                        ws.send('{"type":"ping"}')
            except Exception:
                pass
            finally:
                with self.lock:
                    self.tv_clients.discard(ws)

    def start(self):
        self.server = make_server("0.0.0.0", int(self.cfg.get("hub_port", 5000)), self.app, threaded=True)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        if self.server:
            self.server.shutdown()


if __name__ == "__main__":   # Hub sans interface : python hub_server.py
    from config_manager import Config
    from database import Database
    c = Config()
    h = Hub(Database(c.db_path), c); h.start()
    print(f"Hub actif sur le port {c.get('hub_port', 5000)} — écran TV : /tv")
    threading.Event().wait()
