"""Jetons de session JWT (HS256) émis par le Hub après vérification du PIN ; vérifiés à chaque appel distant."""
import base64, hashlib, hmac, json, secrets, time


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(key, uid, role, ttl=12 * 3600):
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    now = int(time.time())
    body = _b64(json.dumps({"sub": uid, "role": role, "iat": now, "exp": now + ttl, "jti": secrets.token_hex(8)},
                           separators=(",", ":")).encode())
    sig = _b64(hmac.new(key.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest())
    return f"{head}.{body}.{sig}"


def verify_token(key, token):
    """Retourne les claims ou lève ValueError (signature invalide, expiré, malformé)."""
    parts = (token or "").split(".")
    if len(parts) != 3:
        raise ValueError("Session absente : connectez-vous.")
    try:
        head, body, sig = parts
        good = _b64(hmac.new(key.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good) or json.loads(_unb64(head)).get("alg") != "HS256":
            raise ValueError("Jeton invalide.")
        claims = json.loads(_unb64(body))
    except ValueError:
        raise
    except Exception:
        raise ValueError("Jeton illisible.")
    if claims.get("exp", 0) < time.time():
        raise ValueError("Session expirée : reconnectez-vous.")
    return claims
