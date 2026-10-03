"""QR Code (bibliothèque pure Python `segno`, sans dépendance). Retourne None si la bibliothèque est absente."""
from PyQt6.QtGui import QColor, QImage, QPainter


def qr_image(text, scale=8, border=2):
    try:
        import segno
    except ImportError:
        return None
    rows = segno.make(text, error="m").matrix
    n = len(rows) + 2 * border
    img = QImage(n * scale, n * scale, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setPen(QColor("black")); p.setBrush(QColor("black"))
    for y, row in enumerate(rows):
        for x, v in enumerate(row):
            if v:
                p.drawRect((x + border) * scale, (y + border) * scale, scale, scale)
    p.end()
    return img
