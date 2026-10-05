"""Client du Hub LAN : même interface que Database, via RPC HTTP(S). Jeton réseau + JWT utilisateur ; TLS 1.3 avec épinglage du certificat."""
import json, urllib.error, urllib.request

from version import __version__


class HubError(ConnectionError):
    pass


class RemoteDatabase:
    LONG = {"add_result", "get_result", "import_drugs"}

    def __init__(self, host, port, token, timeout=6, use_tls=False, tls_port=5443, cert_pem=""):
        self.http_base = f"http://{host}:{port}"
        self.base = f"https://{host}:{tls_port}" if use_tls else self.http_base
        self.token, self.timeout, self.bearer, self.ctx = token, timeout, None, None
        if use_tls:
            import tls
            self.ctx = tls.client_context(cert_pem)

    def ping(self):
        try:
            with urllib.request.urlopen(self.http_base + "/api/ping", timeout=self.timeout) as r:
                d = json.load(r)
        except Exception as e:
            raise HubError(f"Hub injoignable ({self.http_base}) : {e}")
        if str(d.get("version", "0")).split(".")[0] != __version__.split(".")[0]:
            raise HubError(f"Versions incompatibles : Hub v{d.get('version')} / ce poste v{__version__}. Mettez à jour le poste le plus ancien.")
        return d

    def logout(self):
        self.bearer = None

    def _call(self, method, *a, **k):
        headers = {"Content-Type": "application/json", "X-DEM-Token": self.token}
        if self.bearer:
            headers["Authorization"] = "Bearer " + self.bearer
        req = urllib.request.Request(self.base + "/rpc", data=json.dumps({"m": method, "a": a, "k": k}).encode(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=90 if method in self.LONG else self.timeout, context=self.ctx) as r:
                res = json.load(r)["r"]
        except urllib.error.HTTPError as e:
            try:
                msg = json.load(e).get("error", "")
            except Exception:
                msg = ""
            if e.code == 401:
                self.bearer = None
                raise HubError(msg or "Session expirée : reconnectez-vous.")
            if e.code == 403 and msg == "forbidden":
                raise HubError("Jeton réseau refusé par le Hub (vérifiez le jeton).")
            if e.code == 403:
                raise PermissionError(msg)
            raise HubError(f"Erreur du Hub ({e.code}) {msg}")
        except (urllib.error.URLError, OSError) as e:
            raise HubError(f"Hub injoignable (ou certificat non reconnu) : {e}")
        if method == "verify_pin" and isinstance(res, dict) and res.get("ok"):
            self.bearer = res.get("token")
        return res

    def backup(self, folder):
        raise HubError("La sauvegarde de la base se fait sur le poste Hub.")

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *a, **k: self._call(name, *a, **k)
