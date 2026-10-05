"""Code-barres Code 128 (jeu C : paires de chiffres) pour le N° d'ordonnance — implémentation autonome."""
from PyQt6.QtGui import QColor, QImage, QPainter

_PAT = ("212222 222122 222221 121223 121322 131222 122213 122312 132212 221213 221312 231212 112232 122132 122231 113222 "
        "123122 123221 223211 221132 221231 213212 223112 312131 311222 321122 321221 312212 322112 322211 212123 212321 "
        "232121 111323 131123 131321 112313 132113 132311 211313 231113 231311 112133 112331 132131 113123 113321 133121 "
        "313121 211331 231131 213113 213311 213131 311123 311321 331121 312113 312311 332111 314111 221411 431111 111224 "
        "111422 121124 121421 141122 141221 112214 112412 122114 122411 142112 142211 241211 221114 413111 241112 134111 "
        "111242 121142 121241 114212 124112 124211 411212 421112 421211 212141 214121 412121 111143 111341 131141 114113 "
        "114311 411113 411311 113141 114131 311141 411131 211412 211214 211232").split()
START_C, STOP = 105, "2331112"


def code128c_modules(digits):
    """Retourne la séquence de modules (1 = barre, 0 = espace) du code-barres."""
    if not digits.isdigit() or len(digits) % 2:
        raise ValueError("Code 128-C : nombre pair de chiffres requis.")
    vals = [int(digits[i:i + 2]) for i in range(0, len(digits), 2)]
    check = (START_C + sum(v * (i + 1) for i, v in enumerate(vals))) % 103
    widths = "".join(_PAT[v] for v in [START_C] + vals + [check]) + STOP
    mods, bar = [], 1
    for w in widths:
        mods += [bar] * int(w); bar ^= 1
    return mods


def barcode_image(digits, module=2, height=64, quiet=10):
    mods = code128c_modules(digits)
    img = QImage((len(mods) + 2 * quiet) * module, height, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img); p.setPen(QColor("black")); p.setBrush(QColor("black"))
    for i, m in enumerate(mods):
        if m:
            p.drawRect((quiet + i) * module, 0, module, height)
    p.end()
    return img
