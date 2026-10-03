"""Archivage automatique (fichiers JSON locaux) : accueil -> archives\\reception\\ ; consultations -> archives\\consultations\\.
La base SQLite reste la référence ; ces fichiers sont une copie locale lisible du poste."""
import json, os
from datetime import datetime

from config_manager import data_dir


def _write(kind, name, payload):
    folder = os.path.join(data_dir(), "archives", kind, datetime.now().strftime("%Y-%m-%d"))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    return path


def archive_reception(row):
    return _write("reception", f"{row['ticket_label']}_{row['id']}.json", row)


def archive_consultation(dossier):
    cons, pat = dossier["consultation"], dossier["patient"]
    return _write("consultations", f"consultation_{cons['id']}_{pat['ticket_label']}.json", dossier)
