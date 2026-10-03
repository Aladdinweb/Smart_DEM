"""Configuration locale (config.json), chemins et code PIN administrateur."""
import hashlib, hmac, json, os, secrets, socket, sys

APP_NAME = "Smart_DEM"


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(name):
    return os.path.join(getattr(sys, "_MEIPASS", app_dir()), name)


def data_dir():
    """Dossier des données (DB + config) : séparé du programme, donc jamais touché par la mise à jour."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, APP_NAME)


DEFAULTS = {
    "configured": False,
    "wilaya": "31 - Oran",
    "type": "EPSP",
    "parent": "",
    "structure": "",
    "role": "accueil",            # accueil | dedie | medecin
    "services": [],               # codes de services (poste dédié / médecin)
    "station_name": "",
    "config_version": 2,
    "revisit_check_hours": 72,   # patient récurrent : 72 h
    "doc_printer": "",            # imprimante A4 (ordonnances, demandes)
    "printer": "",                # "" = défaut Windows, "__PDF__" = fichier PDF, sinon nom de l'imprimante
    "paper_width_mm": 80,
    "net_mode": "local",          # local | hub | client
    "hub_host": "",
    "hub_port": 5000,
    "lan_token": "",
    "auto_update_check": True,
    "github_repo": "",            # vide = GITHUB_REPO de version.py
    "theme": "dark",
    "pin_salt": "",
    "pin_hash": "",
}


def _hash(pin, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt_hex), 200_000).hex()


class Config:
    def __init__(self):
        self.dir = data_dir()
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, "config.json")
        self.db_path = os.path.join(self.dir, "dem_database.db")
        self.data = dict(DEFAULTS)
        self.load()
        if not self.data.get("station_name"):
            self.data["station_name"] = socket.gethostname()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                loaded = json.load(f)
            if loaded.get("config_version", 1) < 2:        # v1.0.0 -> v1.1.0
                if loaded.get("revisit_check_hours", 24) == 24:
                    loaded["revisit_check_hours"] = 72
                loaded["config_version"] = 2
            self.data.update(loaded)
        except FileNotFoundError:
            pass
        except json.JSONDecodeError:
            os.replace(self.path, self.path + ".corrupt")

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def update(self, d):
        self.data.update(d)

    # --- PIN administrateur ---
    def has_pin(self):
        return bool(self.data.get("pin_hash"))

    def set_pin(self, pin):
        salt = secrets.token_hex(16)
        self.data["pin_salt"] = salt
        self.data["pin_hash"] = _hash(pin, salt)

    def check_pin(self, pin):
        if not self.has_pin():
            return True
        return hmac.compare_digest(_hash(pin, self.data["pin_salt"]), self.data["pin_hash"])


def local_ip():
    """Adresse IP LAN de ce poste (sans besoin d'internet)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()
