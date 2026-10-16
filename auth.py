"""Jetons de session JWT (HS256) émis par le Hub après vérification du PIN ; vérifiés à chaque appel distant."""
import base64, hashlib, hmac, json, secrets, time

# --- classes d'appels RPC (partagées par le Hub et le client distant) ---
PUBLIC_RPC = {"verify_pin", "list_users", "count_users", "tv_state", "tv_screens",           # jeton réseau seul
              "admin_pin_status", "admin_login", "get_establishment"}
ADMIN_RPC = {"create_user", "update_user", "delete_user", "reset_user_pin", "import_drugs", "tv_set_screens",    # jeton ADMINISTRATEUR (vérifié par le Hub)
             "set_establishment"}
MANAGER_RPC = {"stats_report"}                       # coordinateur (JWT utilisateur) OU administrateur
ADMIN_AWARE_RPC = {"admin_set_pin"}                  # contrôle fait dans la base : 1er PIN libre, ensuite administrateur requis
ADMIN_TTL = 15 * 60                                  # durée d'une session administrateur (secondes)


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
