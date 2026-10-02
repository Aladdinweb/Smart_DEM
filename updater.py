"""Mise à jour en direct depuis un dossier (USB / partage LAN) ou un .zip.
Ne remplace QUE les fichiers du programme : DB et config.json sont protégés (et vivent dans un autre dossier)."""
import os, shutil, subprocess, sys, tempfile, zipfile
from pathlib import Path

PROTECTED = {"dem_database.db", "dem_database.db-wal", "dem_database.db-shm", "config.json", "structures.json", "error.log"}
SKIP_DIRS = {"backups", "tickets"}


def _payload(source):
    src = Path(source)
    tmp = Path(tempfile.mkdtemp(prefix="dem_upd_"))
    if src.is_dir():
        payload = src
    elif src.is_file() and zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as z:
            for n in z.namelist():  # protection zip-slip
                if not (tmp / n).resolve().is_relative_to(tmp.resolve()):
                    raise ValueError("Archive invalide.")
            z.extractall(tmp / "payload")
        payload = tmp / "payload"
        items = list(payload.iterdir())
        if len(items) == 1 and items[0].is_dir():
            payload = items[0]
    else:
        raise ValueError("Sélectionnez un dossier ou un fichier .zip de mise à jour.")
    return tmp, payload


def apply_update(source, target_dir):
    """Retourne (message, quitter_application)."""
    tmp, payload = _payload(source)
    files = [p for p in payload.rglob("*") if p.is_file() and p.name.lower() not in PROTECTED
             and not (set(p.relative_to(payload).parts[:-1]) & SKIP_DIRS)]
    if not any(p.name in ("Smart_DEM.exe", "main.py") for p in files):
        raise ValueError("Ce dossier ne ressemble pas à une mise à jour Smart DEM (Smart_DEM.exe / main.py introuvable).")

    if os.name == "nt" and getattr(sys, "frozen", False):
        # L'exe en cours est verrouillé : un script externe copie après la fermeture, puis relance.
        bat = tmp / "update.bat"
        exe = os.path.join(target_dir, "Smart_DEM.exe")
        bat.write_text(
            "@echo off\r\ntimeout /t 3 /nobreak >nul\r\n"
            f'robocopy "{payload}" "{target_dir}" /E /XD backups tickets /XF dem_database.db dem_database.db-wal dem_database.db-shm config.json structures.json error.log /R:3 /W:2 >nul\r\n'
            f'start "" "{exe}"\r\n', encoding="utf-8")
        subprocess.Popen(["cmd", "/c", str(bat)], creationflags=0x00000008 | 0x08000000, close_fds=True)
        return "La mise à jour va s'appliquer, puis l'application redémarrera.", True

    n = 0
    for p in files:
        dest = Path(target_dir) / p.relative_to(payload)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
        n += 1
    return f"{n} fichier(s) mis à jour. Redémarrez l'application.", False
