"""Modèles personnalisés (trame / fond pré-imprimé : image ou PDF) pour ordonnances, bilans et bons d'examen — impression en surimpression."""
import os, shutil

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QPixmap

from config_manager import data_dir

KINDS = {"ordonnance": "Ordonnance", "bilan": "Bilan de laboratoire", "imagerie": "Bon d'examen (imagerie)"}


def key(kind):
    return f"tpl_{kind}"


def has_template(cfg, kind):
    p = cfg.get(key(kind), "")
    return bool(p) and os.path.isfile(p)


def margins_mm(cfg):
    try:
        t, l, r, b = [float(x) for x in str(cfg.get("tpl_margins_mm", "50,15,15,25")).split(",")]
    except ValueError:
        t, l, r, b = 50, 15, 15, 25
    return t, l, r, b


def import_template(cfg, kind, src):
    """Copie le modèle dans le dossier de données et l'enregistre dans la configuration."""
    folder = os.path.join(data_dir(), "assets", "templates")
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, kind + os.path.splitext(src)[1].lower())
    shutil.copyfile(src, dest)
    cfg.set(key(kind), dest)
    return dest


def load_template(cfg, kind):
    """QPixmap du modèle (1re page si PDF) ou None."""
    if not has_template(cfg, kind):
        return None
    path = cfg.get(key(kind))
    if path.lower().endswith(".pdf"):
        try:
            from PyQt6.QtPdf import QPdfDocument
            doc = QPdfDocument()
            doc.load(path)
            pt = doc.pagePointSize(0)
            w = 1240
            return QPixmap.fromImage(doc.render(0, QSize(w, int(pt.height() * w / pt.width()))))
        except Exception:
            return None
    pix = QPixmap(path)
    return None if pix.isNull() else pix
