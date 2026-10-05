"""Mise à jour en direct depuis un dossier (USB / partage LAN) ou un .zip.
Ne remplace QUE les fichiers du programme : DB et config.json sont protégés (et vivent dans un autre dossier)."""
import os, shutil, subprocess, sys, tempfile, zipfile
from pathlib import Path

PROTECTED = {"dem_database.db", "dem_database.db-wal", "dem_database.db-shm", "config.json", "structures.json", "error.log", "db.key",
             "logo_ministere.png", "update_result.txt"}
SKIP_DIRS = {"backups", "tickets", "documents", "archives", "reports", "tls"}
RESULT_FILE = "update_result.txt"


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


def build_update_script(payload, target_dir, exe, pid, result_file, wait_seconds=300):
    """Script exécuté APRÈS la fermeture de l'application (attend la fin du processus), copie les fichiers, note le résultat, relance."""
    xd = " ".join(sorted(SKIP_DIRS))
    xf = " ".join(sorted(PROTECTED))
    return "\r\n".join([
        "@echo off", "chcp 65001 >nul", "setlocal",
        f'set "PID={pid}"', f'set "RESULT={result_file}"', "set /a N=0",
        ":wait",
        'tasklist /FI "PID eq %PID%" 2>nul | find "%PID%" >nul',
        "if errorlevel 1 goto go",
        "set /a N+=1",
        f"if %N% GEQ {wait_seconds} goto timeout",
        "timeout /t 1 /nobreak >nul", "goto wait",
        ":timeout", 'echo TIMEOUT> "%RESULT%"', "exit /b 1",          # l'application n'a pas été fermée : on ne touche à rien
        ":go", "timeout /t 2 /nobreak >nul",
        f'robocopy "{payload}" "{target_dir}" /E /XD {xd} /XF {xf} /R:30 /W:2 /NFL /NDL /NP /NJH /NJS',
        "set RC=%ERRORLEVEL%",
        'if %RC% GEQ 8 (echo FAILED %RC%> "%RESULT%") else (echo OK %RC%> "%RESULT%")',
        f'start "" "{exe}"', "exit /b 0", ""])


def apply_update(source, target_dir):
    """Retourne (message, quitter_application). Sous Windows (version installée) la copie est différée jusqu'à la fermeture réelle de l'application."""
    from config_manager import data_dir
    tmp, payload = _payload(source)
    files = [p for p in payload.rglob("*") if p.is_file() and p.name.lower() not in PROTECTED
             and not (set(p.relative_to(payload).parts[:-1]) & SKIP_DIRS)]
    if not any(p.name in ("Smart_DEM.exe", "main.py") for p in files):
        raise ValueError("Ce dossier ne ressemble pas à une mise à jour Smart DEM (Smart_DEM.exe / main.py introuvable).")

    if os.name == "nt" and getattr(sys, "frozen", False):
        bat = tmp / "update.bat"
        bat.write_text(build_update_script(payload, target_dir, os.path.join(target_dir, "Smart_DEM.exe"), os.getpid(),
                                           os.path.join(data_dir(), RESULT_FILE)), encoding="utf-8")
        subprocess.Popen(["cmd", "/c", str(bat)], creationflags=0x08000000 | 0x00000200, close_fds=True)   # sans fenêtre, indépendant
        return "L'application va se fermer puis redémarrer automatiquement avec la nouvelle version.", True

    n = 0
    for p in files:
        dest = Path(target_dir) / p.relative_to(payload)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
        n += 1
    return f"{n} fichier(s) mis à jour. Redémarrez l'application.", False
