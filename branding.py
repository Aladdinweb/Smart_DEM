"""En-tête officiel : logo du Ministère (gauche) + République/Ministère (centre) + drapeau (droite), même taille, format cercle."""
import math, os

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from config_manager import data_dir, resource_path

GREEN, RED = "#006233", "#D21034"
TITLE = "République Algérienne Démocratique et Populaire"
MINISTRY = "Ministère de la Santé"


def _blank(d):
    p = QPixmap(d, d)
    p.fill(Qt.GlobalColor.transparent)
    return p


def _painter(pix):
    pt = QPainter(pix)
    pt.setRenderHint(QPainter.RenderHint.Antialiasing)
    pt.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    return pt


def _clip_circle(pt, d):
    path = QPainterPath()
    path.addEllipse(0, 0, d, d)
    pt.setClipPath(path)


def _ring(pt, d):
    pt.setClipping(False)
    pt.setBrush(Qt.BrushStyle.NoBrush)
    pt.setPen(QPen(QColor("#9aa5b1"), max(1.0, d / 48)))
    pt.drawEllipse(QRectF(0.5, 0.5, d - 1, d - 1))


def _star(cx, cy, r):
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.382
        pts.append(QPointF(cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    return QPolygonF(pts)


def flag_pixmap(d):
    """Drapeau d'Algérie en dôme circulaire (vert / blanc, croissant et étoile rouges)."""
    pix = _blank(d)
    pt = _painter(pix)
    _clip_circle(pt, d)
    pt.fillRect(QRectF(0, 0, d / 2, d), QColor(GREEN))
    pt.fillRect(QRectF(d / 2, 0, d / 2, d), QColor("white"))
    cres = _blank(d)
    cp = _painter(cres)
    cp.setPen(Qt.PenStyle.NoPen)
    cp.setBrush(QColor(RED))
    cp.drawEllipse(QPointF(d * 0.5, d * 0.5), d * 0.26, d * 0.26)
    cp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)   # découpe le croissant
    cp.drawEllipse(QPointF(d * 0.57, d * 0.5), d * 0.21, d * 0.21)
    cp.end()
    pt.drawPixmap(0, 0, cres)
    pt.setPen(Qt.PenStyle.NoPen)
    pt.setBrush(QColor(RED))
    pt.drawPolygon(_star(d * 0.58, d * 0.5, d * 0.11))
    _ring(pt, d)
    pt.end()
    return pix


def logo_path():
    for p in (os.path.join(data_dir(), "assets", "logo_ministere.png"), resource_path(os.path.join("assets", "logo_ministere.png"))):
        if os.path.isfile(p):
            return p
    return None


def ministry_pixmap(d):
    """Logo officiel (assets/logo_ministere.png) rogné en cercle, de la même taille que le drapeau ; None s'il n'a pas été fourni."""
    p = logo_path()
    src = QPixmap(p) if p else QPixmap()
    if src.isNull():
        return None
    pix = _blank(d)
    pt = _painter(pix)
    _clip_circle(pt, d)
    pt.fillRect(0, 0, d, d, QColor("white"))
    s = src.scaled(d, d, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    pt.drawPixmap((d - s.width()) // 2, (d - s.height()) // 2, s)
    _ring(pt, d)
    pt.end()
    return pix


def import_logo(src_path):
    """Enregistre le logo officiel fourni (PNG/JPG) dans le dossier de données : actif immédiatement, sans réinstaller."""
    img = QPixmap(src_path)
    if img.isNull():
        raise ValueError("Image illisible.")
    folder = os.path.join(data_dir(), "assets")
    os.makedirs(folder, exist_ok=True)
    img.scaled(600, 600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation).save(os.path.join(folder, "logo_ministere.png"), "PNG")


def print_resources(d=220):
    """Images nommées utilisables dans le HTML des documents imprimés (<img src="drapeau">)."""
    res = {"drapeau": flag_pixmap(d)}
    logo = ministry_pixmap(d)
    if logo is not None:
        res["logo_ministere"] = logo
    return res


def establishment(cfg):
    return " - ".join(x for x in (cfg.get("parent", ""), cfg.get("structure", "")) if x)


class HeaderBar(QFrame):
    """Bandeau officiel affiché en haut de toutes les vues : logo (gauche), République / Ministère / établissement (centre), drapeau (droite)."""
    def __init__(self, cfg=None, d=64):
        super().__init__()
        self.setObjectName("card")
        h = QHBoxLayout(self)
        left, right = QLabel(), QLabel()
        logo = ministry_pixmap(d)
        if logo is not None:
            left.setPixmap(logo)
        right.setPixmap(flag_pixmap(d))
        for lab in (left, right):
            lab.setFixedSize(d, d)
        mid = QVBoxLayout()
        lines = [(TITLE, f"font-size:{max(12, d // 4)}px;font-weight:700;"), (MINISTRY, f"font-size:{max(11, d // 4 - 1)}px;font-weight:600;color:#8b97a7;")]
        name = establishment(cfg) if cfg is not None else ""
        if name:
            lines.append((name, f"font-size:{max(12, d // 4)}px;font-weight:800;color:#4f9dff;"))
        for text, style in lines:
            lab = QLabel(text); lab.setStyleSheet(style); lab.setAlignment(Qt.AlignmentFlag.AlignCenter); lab.setTextFormat(Qt.TextFormat.PlainText)
            mid.addWidget(lab)
        h.addWidget(left); h.addLayout(mid, 1); h.addWidget(right)
