"""Client du Hub LAN : même interface que Database, via un appel RPC HTTP (réseau local, sans internet)."""
import json, urllib.error, urllib.request

from version import __version__


class HubError(ConnectionError):
    pass


class RemoteDatabase:
    def __init__(self, host, port, token, timeout=6):
        self.base, self.token, self.timeout = f"http://{host}:{port}", token, timeout

    def ping(self):
        try:
            with urllib.request.urlopen(self.base + "/api/ping", timeout=self.timeout) as r:
                d = json.load(r)
        except Exception as e:
            raise HubError(f"Hub injoignable ({self.base}) : {e}")
        if str(d.get("version", "0")).split(".")[0] != __version__.split(".")[0]:
            raise HubError(f"Versions incompatibles : Hub v{d.get('version')} / ce poste v{__version__}. Mettez à jour le poste le plus ancien.")
        return d

    def _call(self, method, *a, **k):
        req = urllib.request.Request(self.base + "/rpc", data=json.dumps({"m": method, "a": a, "k": k}).encode(),
                                     headers={"Content-Type": "application/json", "X-DEM-Token": self.token})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.load(r)["r"]
        except urllib.error.HTTPError as e:
            if e.code == 403:
                raise HubError("Jeton réseau refusé par le Hub (vérifiez le jeton).")
            try:
                msg = json.load(e).get("error", "")
            except Exception:
                msg = ""
            raise HubError(f"Erreur du Hub ({e.code}) {msg}")
        except (urllib.error.URLError, OSError) as e:
            raise HubError(f"Hub injoignable : {e}")

    def backup(self, folder):
        raise HubError("La sauvegarde de la base se fait sur le poste Hub.")

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *a, **k: self._call(name, *a, **k)
