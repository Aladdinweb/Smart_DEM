"""Interface adaptative 4:3 / 16:9 (v1.4.0) : profil d'écran (format, compacité), contrôle du format dans la configuration, et garde-fou qui
empêche toute fenêtre de dépasser la taille de l'écran (ex : 1024×768)."""
from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QDialog

FORMATS = {"auto": "Automatique (selon l'écran)", "4:3": "4:3 — compact", "16:9": "16:9 — large"}


def ratio_name(ratio):
    if ratio < 1.45:
        return "4:3"                       # 4:3 (1.33) et 5:4 (1.25)
    if ratio < 1.7:
        return "16:10"
    return "16:9"


def profile(cfg=None, screen=None):
    """{'w','h','ratio','name','compact','two_rows'} pour l'écran principal ; le réglage `screen_format` de la configuration peut forcer 4:3 ou 16:9.
    compact  : polices / marges réduites (écrans 4:3 ou petits) ; two_rows : boutons d'en-tête sur une 2e ligne (largeur limitée)."""
    scr = screen or QGuiApplication.primaryScreen()
    g = scr.availableGeometry() if scr else None
    w, h = (g.width(), g.height()) if g else (1366, 768)
    ratio = w / max(1, h)
    name = ratio_name(ratio)
    forced = (cfg.get("screen_format", "auto") if cfg is not None else "auto")
    if forced == "4:3":
        name = "4:3"
    elif forced == "16:9":
        name = "16:9"
    compact = name == "4:3" and w < 1500 or w < 1180 or h < 700
    if forced == "16:9":
        compact = w < 1180 or h < 700
    two_rows = name == "4:3" or w < 1500
    if forced == "16:9":
        two_rows = w < 1500
    return {"w": w, "h": h, "ratio": ratio, "name": name, "compact": compact, "two_rows": two_rows}


class _Fit(QObject):
    """Réduit toute fenêtre de dialogue plus grande que l'écran disponible (le contenu défile / se compresse au lieu de déborder)."""
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Show and isinstance(obj, QDialog) and obj.isWindow():
            scr = obj.screen() or QGuiApplication.primaryScreen()
            if scr:
                g = scr.availableGeometry()
                mw, mh = int(g.width() * 0.96), int(g.height() * 0.94)
                if obj.width() > mw or obj.height() > mh:
                    obj.resize(min(obj.width(), mw), min(obj.height(), mh))
                    obj.move(g.x() + (g.width() - obj.width()) // 2, g.y() + (g.height() - obj.height()) // 2)
        return False


_fit = None


def install_screen_fit(app):
    global _fit
    if _fit is None:
        _fit = _Fit(app)
        app.installEventFilter(_fit)


from PyQt6.QtCore import QPoint, QRect, QSize, Qt  # noqa: E402
from PyQt6.QtWidgets import QLayout  # noqa: E402


class FlowLayout(QLayout):
    """Boutons alignés sur une ligne, renvoyés à la ligne si la largeur manque (en-têtes sur écrans 4:3 / 1024 px)."""
    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items, self._sp = [], spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item): self._items.append(item)
    def count(self): return len(self._items)
    def itemAt(self, i): return self._items[i] if 0 <= i < len(self._items) else None
    def takeAt(self, i): return self._items.pop(i) if 0 <= i < len(self._items) else None
    def expandingDirections(self): return Qt.Orientation(0)
    def hasHeightForWidth(self): return True
    def heightForWidth(self, w): return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):                                    # largeur préférée = tous les boutons sur une seule ligne
        vis = [i for i in self._items if not i.isEmpty()]
        m = self.contentsMargins()
        w = sum(i.sizeHint().width() for i in vis) + self._sp * max(0, len(vis) - 1) + m.left() + m.right()
        h = max([i.sizeHint().height() for i in vis] or [0]) + m.top() + m.bottom()
        return QSize(w, h)

    def minimumSize(self):                                 # largeur minimale = le plus large des boutons
        vis = [i for i in self._items if not i.isEmpty()]
        m = self.contentsMargins()
        return QSize(max([i.minimumSize().width() for i in vis] or [0]) + m.left() + m.right(),
                     max([i.minimumSize().height() for i in vis] or [0]) + m.top() + m.bottom())

    def _do(self, rect, test):
        m = self.contentsMargins()
        x0, x, y, lh, right = rect.x() + m.left(), rect.x() + m.left(), rect.y() + m.top(), 0, rect.right() - m.right()
        for it in self._items:
            if it.isEmpty():
                continue
            sh = it.sizeHint()
            if x + sh.width() > right + 1 and lh > 0:
                x, y, lh = x0, y + lh + self._sp, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), sh))
            x += sh.width() + self._sp
            lh = max(lh, sh.height())
        return y + lh - rect.y() + m.bottom()
