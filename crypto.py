"""Chiffrement AES-256-GCM des données cliniques au repos (champs de la base). Clé : <dossier de données>\\db.key.
Sans la bibliothèque `cryptography`, les données restent en clair (indiqué dans Paramètres)."""
import base64, os, secrets

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAVE = True
except ImportError:  # pragma: no cover
    HAVE = False

PREFIX = "enc1:"


class Crypto:
    def __init__(self, key=None):
        self.aes = AESGCM(key) if (HAVE and key) else None
        self.key_path = None

    @property
    def available(self):
        return self.aes is not None

    @classmethod
    def for_dir(cls, folder):
        """Charge (ou crée au premier lancement) la clé 256 bits `db.key` du dossier de données."""
        if not HAVE:
            return cls(None)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "db.key")
        if os.path.exists(path):
            with open(path, "rb") as f:
                key = f.read()
        else:
            key = secrets.token_bytes(32)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(key)
        if len(key) != 32:
            raise ValueError("Fichier db.key invalide (32 octets attendus).")
        c = cls(key)
        c.key_path = path
        return c

    def enc(self, text):
        if text is None or text == "" or not self.aes:
            return text
        nonce = os.urandom(12)
        return PREFIX + base64.b64encode(nonce + self.aes.encrypt(nonce, text.encode("utf-8"), None)).decode()

    def dec(self, value):
        if not isinstance(value, str) or not value.startswith(PREFIX):
            return value            # donnée ancienne non chiffrée : lue telle quelle
        if not self.aes:
            raise RuntimeError("Clé de chiffrement absente (db.key) : données cliniques illisibles.")
        raw = base64.b64decode(value[len(PREFIX):])
        return self.aes.decrypt(raw[:12], raw[12:], None).decode("utf-8")
