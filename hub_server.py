"""Hub LAN : RPC sécurisé (jeton réseau + JWT par utilisateur, HTTPS/TLS 1.3 optionnel), WebSocket des écrans TV (/ws/tv),
dispatching par service et par écran. Fonctionne SANS internet : aucune ressource externe."""
import hmac, json, os, random, secrets, threading, time

from flask import Flask, Response, jsonify, request
from flask_sock import Sock
from werkzeug.serving import make_server

from auth import ADMIN_AWARE_RPC, ADMIN_RPC, ADMIN_TTL, MANAGER_RPC, PUBLIC_RPC, make_token, verify_token
from config_manager import data_dir
from data_structures import SERVICE_BY_CODE, SERVICE_COLORS
from database import RPC_METHODS
from tv_page import TV_HTML
from version import __version__

CURRENT = None   # instance active (pour le bouton « Tester l'écran TV »)
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
        self.pending, self.announcements = {}, []          # codes d'appariement en attente, bandeaux d'annonce actifs
        db.tv_pair_hook = self.bind_code
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
            self.state = {"message": ev["message"], "paused": ev["paused"], "voice": ev.get("voice", True)}
        elif ev["type"] == "clear":
            with self.lock:
                self.recent.clear()
        elif ev["type"] == "announce":
            with self.lock:
                self.announcements = [a for a in self._active_announcements() if a["id"] != ev["id"]] + [{**ev, "expires": time.time() + ev["seconds"]}]
        elif ev["type"] == "announce_clear":
            with self.lock:
                self.announcements = [] if ev["id"] == "*" else [a for a in self.announcements if a["id"] != ev["id"]]
        self._broadcast(ev)

    def _active_announcements(self):
        return [a for a in self.announcements if a["expires"] > time.time()]

    # --- appariement d'une TV par code court (TV-4092) ---
    def new_code(self):
        now = time.time()
        self.pending = {c: v for c, v in self.pending.items() if now - v["ts"] < 600}
        if len(self.pending) >= 30:
            return None, None
        code = next(c for c in (f"{random.randint(0, 9999):04d}" for _ in range(200)) if c not in self.pending)
        token = secrets.token_hex(16)
        self.pending[code] = {"token": token, "ts": now}
        return code, token

    def bind_code(self, code):
        """Appelé par la base quand l'accueil saisit un code : retourne le jeton de la TV (et libère le code) ou None."""
        c = "".join(ch for ch in str(code) if ch.isdigit())[-4:]
        v = self.pending.get(c)
        if v and time.time() - v["ts"] < 600:
            self.pending[c]["bound"] = True
            return v["token"]
        return None

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
            uid, admin = None, False
            auth_h = request.headers.get("Authorization", "")
            bearer = auth_h[7:] if auth_h.startswith("Bearer ") else ""
            claims = None
            if bearer or not (m in PUBLIC_RPC or m in ADMIN_AWARE_RPC):          # jeton facultatif pour les appels publics, sinon obligatoire
                try:
                    claims = verify_token(self.db.jwt_secret(), bearer)
                except ValueError as e:
                    if m not in PUBLIC_RPC and m not in ADMIN_AWARE_RPC:
                        return jsonify({"error": str(e)}), 401
            if claims is not None:
                admin = claims.get("role") == "admin"
                uid = None if admin else claims["sub"]
            if m in ADMIN_RPC and not admin:                                      # sécurité réseau : le PIN administrateur est vérifié ICI, pas dans l'interface
                return jsonify({"error": "Authentification administrateur requise (PIN vérifié par le Hub)."}), 403
            if m in MANAGER_RPC and not (admin or uid is not None):
                return jsonify({"error": "Session invalide : reconnectez-vous."}), 401
            if m in SELF_ONLY and (not a or a[0] != uid):
                return jsonify({"error": "Action réservée à votre propre compte."}), 403
            self.db._ctx.uid, self.db._ctx.remote, self.db._ctx.admin = uid, True, admin     # l'identité vient du jeton, pas des arguments
            try:
                result = getattr(self.db, m)(*a, **k)
            except PermissionError as e:
                return jsonify({"error": str(e)}), 403
            except Exception as e:
                return jsonify({"error": str(e)}), 500
            finally:
                self.db._ctx.uid, self.db._ctx.remote, self.db._ctx.admin = None, False, False
            if m == "verify_pin" and isinstance(result, dict) and result.get("ok"):
                u = result["user"]
                result["token"] = make_token(self.db.jwt_secret(), u["id"], u["role"])
            if m == "admin_login" and isinstance(result, dict) and result.get("ok"):
                result["token"] = make_token(self.db.jwt_secret(), 0, "admin", ADMIN_TTL)
            return jsonify({"r": result})

        @app.post("/api/tv/pair")
        def tv_pair_new():                                    # public : la TV n'est qu'un navigateur ; le code n'ouvre aucun accès
            code, token = self.new_code()
            if not code:
                return jsonify({"error": "trop de codes en attente"}), 429
            return jsonify({"code": f"TV-{code}", "token": token})

        @app.get("/api/tv/pair/<token>")
        def tv_pair_status(token):
            screen = self.db.tv_binding(token)
            s = next((x for x in self.db.tv_screens() if x["id"] == screen), None) if screen else None
            pending = any(v["token"] == token and time.time() - v["ts"] < 600 for v in self.pending.values())
            return jsonify({"bound": bool(s), "screen": s["id"] if s else "", "name": s["name"] if s else "", "pending": pending})

        @app.get("/tv")
        def tv():
            return Response(TV_HTML, mimetype="text/html; charset=utf-8")

        @self.sock.route("/ws/tv")
        def ws_tv(ws):
            wanted = request.args.get("screen") or self.db.tv_binding(request.args.get("token", ""))
            screen = next((s for s in self.db.tv_screens() if s["id"] == wanted), None)
            services = set(screen["services"]) if screen and screen["services"] else None
            with self.lock:
                self.tv_clients[ws] = services
                ws.send(json.dumps({"type": "snapshot", "recent": [] if self.state.get("paused") else self._recent_for(services),
                                    "state": self.state, "screen": screen["name"] if screen else "",
                                    "announcements": [{"id": a["id"], "text": a["text"], "level": a["level"], "seconds": int(a["expires"] - time.time())}
                                                      for a in self._active_announcements()]}, ensure_ascii=False))
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
