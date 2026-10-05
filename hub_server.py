"""Hub LAN : RPC sécurisé (jeton réseau + JWT par utilisateur, HTTPS/TLS 1.3 optionnel), WebSocket des écrans TV (/ws/tv),
dispatching par service et par écran. Fonctionne SANS internet : aucune ressource externe."""
import hmac, json, os, threading, time

from flask import Flask, Response, jsonify, request
from flask_sock import Sock
from werkzeug.serving import make_server

from auth import make_token, verify_token
from config_manager import data_dir
from data_structures import SERVICE_BY_CODE, SERVICE_COLORS
from database import RPC_METHODS
from tv_page import TV_HTML
from version import __version__

CURRENT = None   # instance active (pour le bouton « Tester l'écran TV »)
PUBLIC_RPC = {"verify_pin", "list_users", "count_users", "tv_state", "tv_screens"}                      # jeton réseau seul
ADMIN_RPC = {"create_user", "update_user", "delete_user", "reset_user_pin", "import_drugs", "tv_set_screens", "stats_report"}
SELF_ONLY = {"set_user_image", "set_signature", "change_own_pin", "get_user"}                           # 1er argument = l'utilisateur du jeton


class Hub:
    def __init__(self, db, cfg):
        global CURRENT
        self.db, self.cfg = db, cfg
        self.tv_clients, self.recent, self.lock, self.server, self.tls_server = {}, [], threading.Lock(), None, None
        self.tls_required = bool(cfg.get("hub_tls"))
        self.app = Flask(__name__)
        self.sock = Sock(self.app)
        self._routes()
        db.call_listeners.append(self.on_call)
        db.tv_listeners.append(self.on_tv)
        self.state = db.tv_state()
        CURRENT = self

    # --- diffusion vers les écrans TV : numéro + service + bureau UNIQUEMENT (secret médical : jamais de nom de patient) ---
    def on_call(self, row, is_recall, room):
        if self.state.get("paused"):                     # l'accueil a mis l'affichage en pause
            return
        code = row["service_code"]
        svc = SERVICE_BY_CODE.get(code, {})
        ev = {"type": "call", "ticket": row["ticket_label"], "service_id": code, "icon": svc.get("icon", ""), "service": svc.get("name", ""),
              "color": SERVICE_COLORS.get(code, "#4f9dff"), "room": room, "recall": bool(is_recall), "at": time.strftime("%H:%M")}
        with self.lock:
            self.recent.insert(0, ev); del self.recent[40:]
        self._broadcast(ev)

    def on_tv(self, ev):
        """Pilotage depuis l'accueil : message défilant, pause, effacement, mise à jour de la configuration des écrans."""
        if ev["type"] == "state":
            self.state = {"message": ev["message"], "paused": ev["paused"]}
        elif ev["type"] == "clear":
            with self.lock:
                self.recent.clear()
        self._broadcast(ev)

    @staticmethod
    def _wanted(services, ev):
        return ev["type"] != "call" or not services or ev["service_id"] in services

    def _recent_for(self, services):
        return [e for e in self.recent if self._wanted(services, e)][:8]

    def _broadcast(self, ev):
        msg = json.dumps(ev, ensure_ascii=False)
        with self.lock:
            for ws, services in list(self.tv_clients.items()):
                if not self._wanted(services, ev):       # filtrage : seule la TV concernée reçoit le signal
                    continue
                try:
                    ws.send(msg)
                except Exception:
                    self.tv_clients.pop(ws, None)

    def test_call(self):
        self.on_call({"ticket_label": "TEST-000", "service_code": "LAB"}, False, "Test écran TV")

    def _authorized(self):
        token = self.cfg.get("lan_token", "")
        return bool(token) and hmac.compare_digest(request.headers.get("X-DEM-Token", ""), token)

    def _routes(self):
        app, cfg = self.app, self.cfg

        @app.get("/api/ping")
        def ping():
            return jsonify({"ok": True, "version": __version__, "tls": self.tls_required,
                            "name": f"{cfg.get('parent', '')} — {cfg.get('structure', '')}"})

        @app.post("/rpc")
        def rpc():
            if self.tls_required and request.environ.get("wsgi.url_scheme") != "https":
                return jsonify({"error": "HTTPS requis"}), 403
            if not self._authorized():
                return jsonify({"error": "forbidden"}), 403
            d = request.get_json(force=True, silent=True) or {}
            m, a, k = d.get("m"), d.get("a", []), d.get("k", {})
            if m not in RPC_METHODS:
                return jsonify({"error": "méthode inconnue (mettez à jour le Hub ?)"}), 400
            uid = None
            if m not in PUBLIC_RPC and m not in ADMIN_RPC:           # appel utilisateur : jeton JWT obligatoire
                auth = request.headers.get("Authorization", "")
                try:
                    claims = verify_token(self.db.jwt_secret(), auth[7:] if auth.startswith("Bearer ") else "")
                except ValueError as e:
                    return jsonify({"error": str(e)}), 401
                uid = claims["sub"]
                if m in SELF_ONLY and (not a or a[0] != uid):
                    return jsonify({"error": "Action réservée à votre propre compte."}), 403
            self.db._ctx.uid = uid                                    # l'identité vient du jeton, pas des arguments
            try:
                result = getattr(self.db, m)(*a, **k)
            except PermissionError as e:
                return jsonify({"error": str(e)}), 403
            except Exception as e:
                return jsonify({"error": str(e)}), 500
            finally:
                self.db._ctx.uid = None
            if m == "verify_pin" and isinstance(result, dict) and result.get("ok"):
                u = result["user"]
                result["token"] = make_token(self.db.jwt_secret(), u["id"], u["role"])
            return jsonify({"r": result})

        @app.get("/tv")
        def tv():
            return Response(TV_HTML, mimetype="text/html; charset=utf-8")

        @self.sock.route("/ws/tv")
        def ws_tv(ws):
            screen = next((s for s in self.db.tv_screens() if s["id"] == request.args.get("screen")), None)
            services = set(screen["services"]) if screen and screen["services"] else None
            with self.lock:
                self.tv_clients[ws] = services
                ws.send(json.dumps({"type": "snapshot", "recent": [] if self.state.get("paused") else self._recent_for(services),
                                    "state": self.state, "screen": screen["name"] if screen else ""}, ensure_ascii=False))
            try:
                while True:
                    if ws.receive(timeout=25) is None:      # silence : battement de coeur
                        ws.send('{"type":"ping"}')
            except Exception:
                pass
            finally:
                with self.lock:
                    self.tv_clients.pop(ws, None)

    def start(self):
        self.server = make_server("0.0.0.0", int(self.cfg.get("hub_port", 5000)), self.app, threaded=True)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        if self.tls_required:
            import tls
            cert, key = tls.ensure_cert(os.path.join(data_dir(), "tls"))
            self.tls_server = make_server("0.0.0.0", int(self.cfg.get("hub_tls_port", 5443)), self.app, threaded=True,
                                          ssl_context=tls.server_context(cert, key))
            threading.Thread(target=self.tls_server.serve_forever, daemon=True).start()

    def stop(self):
        for s in (self.server, self.tls_server):
            if s:
                s.shutdown()


if __name__ == "__main__":   # Hub sans interface : python hub_server.py
    from config_manager import Config
    from database import Database
    c = Config()
    h = Hub(Database(c.db_path), c); h.start()
    print(f"Hub actif sur le port {c.get('hub_port', 5000)} — écran TV : /tv")
    threading.Event().wait()
