"""Dossier local de chaque agent : <données>\\data\\users\\NOM_PRENOM_00012\\ -> profile.json, activity.log, drafts\\.
Reflet local de la base (la base reste la référence) : identité/fonction, historique des actions faites SUR CE PC (sans nom de patient :
numéros de ticket uniquement) et copie des brouillons de consultation."""
import json, os, re, unicodedata
from datetime import datetime

from config_manager import data_dir

MAX_LOG = 5 * 1024 * 1024


def _ascii(s):
    s = unicodedata.normalize("NFKD", s or "")
    return re.sub(r"[^A-Z0-9]+", "_", "".join(c for c in s if not unicodedata.combining(c)).upper()).strip("_")


def slug(user):
    return f"{_ascii(user['last_name'])}_{_ascii(user['first_name'])}_{int(user['id']):05d}"


def user_dir(user):
    d = os.path.join(data_dir(), "data", "users", slug(user))
    os.makedirs(os.path.join(d, "drafts"), exist_ok=True)
    return d


def write_profile(user, station=""):
    p = {"id": user["id"], "nom": user["last_name"], "prenom": user["first_name"], "fonction": user.get("function"), "espace": user["role"],
         "specialite": user.get("specialty", ""), "services": user.get("services", []), "poste": station,
         "derniere_connexion": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    path = os.path.join(user_dir(user), "profile.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)
    return path


def log_activity(user, action, detail="", station=""):
    """Une ligne par action : date | poste | action | détail (jamais d'identité de patient)."""
    path = os.path.join(user_dir(user), "activity.log")
    try:
        if os.path.exists(path) and os.path.getsize(path) > MAX_LOG:
            os.replace(path, path + ".1")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} | {station} | {action} | {detail}\n")
    except OSError:
        pass


def save_draft(user, key, data):
    path = os.path.join(user_dir(user), "drafts", f"{_ascii(key)}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "data": data}, f, ensure_ascii=False)
    return path


def delete_draft(user, key):
    try:
        os.remove(os.path.join(user_dir(user), "drafts", f"{_ascii(key)}.json"))
    except OSError:
        pass
