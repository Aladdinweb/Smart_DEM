"""Vérification des mises à jour via l'API GitHub Releases (dépôt public) + téléchargement vérifié.
L'installation réutilise updater.apply_update : la base SQLite et config.json ne sont jamais touchés."""
import hashlib, json, os, re, sys, tempfile, urllib.error, urllib.request

import updater
from config_manager import app_dir
from version import __version__

ASSET_ZIP = "Smart_DEM_update.zip"
ASSET_SHA = ASSET_ZIP + ".sha256"
_SEMVER = re.compile(r"v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?")


class UpdateError(Exception):
    pass


def parse_semver(v):
    m = _SEMVER.fullmatch((v or "").strip())
    if not m:
        return None
    maj, mi, pa, pre = m.groups()
    # une pré-version (1.0.0-rc.1) est antérieure à la version finale (1.0.0)
    return (int(maj), int(mi), int(pa), 0 if pre else 1, pre or "")


def is_newer(remote, local=__version__):
    r, l = parse_semver(remote), parse_semver(local)
    return bool(r and l and r > l)


def _req(url, accept="application/vnd.github+json"):
    return urllib.request.Request(url, headers={"User-Agent": "Smart-DEM-Updater", "Accept": accept,
                                                "X-GitHub-Api-Version": "2022-11-28"})


def check_latest(repo, current=__version__, timeout=8):
    """Interroge /repos/{repo}/releases/latest. Retourne un dict d'information."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        with urllib.request.urlopen(_req(url), timeout=timeout) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError("Aucune release publiée (ou dépôt introuvable / privé).")
        if e.code in (403, 429):
            raise UpdateError("Limite de l'API GitHub atteinte. Réessayez plus tard.")
        raise UpdateError(f"Erreur GitHub ({e.code}).")
    except (urllib.error.URLError, OSError):
        raise UpdateError("Pas de connexion à GitHub (internet requis). Utilisez la mise à jour hors ligne si besoin.")
    tag = d.get("tag_name", "")
    assets = {a["name"]: a["browser_download_url"] for a in d.get("assets", [])}
    return {"available": is_newer(tag, current), "version": tag.lstrip("v"), "current": current,
            "notes": d.get("body") or "", "page": d.get("html_url", ""),
            "zip_url": assets.get(ASSET_ZIP), "sha_url": assets.get(ASSET_SHA)}


def download_update(info, progress_cb=lambda p: None):
    """Télécharge Smart_DEM_update.zip dans un dossier temporaire et vérifie son SHA-256 (si publié)."""
    if not info.get("zip_url"):
        raise UpdateError(f"La release ne contient pas {ASSET_ZIP}.")
    path = os.path.join(tempfile.mkdtemp(prefix="dem_dl_"), ASSET_ZIP)
    h = hashlib.sha256()
    with urllib.request.urlopen(_req(info["zip_url"], "application/octet-stream"), timeout=30) as r, open(path, "wb") as f:
        total, done = int(r.headers.get("Content-Length") or 0), 0
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            f.write(chunk); h.update(chunk); done += len(chunk)
            if total:
                progress_cb(int(done * 100 / total))
    if info.get("sha_url"):
        with urllib.request.urlopen(_req(info["sha_url"], "application/octet-stream"), timeout=15) as r:
            expected = r.read().decode().split()[0].lower()
        if expected != h.hexdigest():
            os.remove(path)
            raise UpdateError("Somme de contrôle SHA-256 invalide : téléchargement corrompu, mise à jour annulée.")
    return path


def install(zip_path):
    """Extrait/applique le ZIP dans le dossier d'installation (%LOCALAPPDATA%\\Smart_DEM). Retourne (message, quitter)."""
    if not getattr(sys, "frozen", False):
        raise UpdateError("L'installation automatique n'est disponible que dans la version installée (Smart_DEM.exe).")
    return updater.apply_update(zip_path, app_dir())
