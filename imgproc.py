"""Traitement de la griffe / signature : suppression automatique du fond (blanc ou grisé) -> PNG transparent, rognage, contraste."""
import io

from PIL import Image, ImageOps, ImageStat


def _open(source):
    img = Image.open(io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source)
    return ImageOps.exif_transpose(img).convert("RGBA")


def _border_median(gray):
    w, h = gray.size
    m = max(2, min(w, h) // 40)
    px = gray.load()
    vals = [px[x, y] for x in range(w) for y in (*range(m), *range(h - m, h))] + [px[x, y] for y in range(m, h - m) for x in (*range(m), *range(w - m, w))]
    vals.sort()
    return vals[len(vals) // 2] if vals else 255


def process(source, threshold=28, softness=70, contrast=1.0, crop=(0, 0, 0, 0), keep_color=True, trim=True, max_size=(900, 450)):
    """crop = (gauche, haut, droite, bas) en % ; retourne les octets d'un PNG RGBA (fond transparent)."""
    img = _open(source)
    img.thumbnail(max_size, Image.LANCZOS)
    w, h = img.size
    l, t, r, b = [max(0, min(45, c)) / 100 for c in crop]
    img = img.crop((int(w * l), int(h * t), w - int(w * r), h - int(h * b)))
    alpha_src = img.getchannel("A")
    if alpha_src.getextrema()[0] < 250:                       # image déjà transparente : on conserve son canal alpha
        alpha = alpha_src
    else:
        gray = img.convert("L")
        bg = _border_median(gray)                             # niveau du fond (blanc, gris de scanner…)
        lut = [max(0, min(255, int(((bg - v) * contrast - threshold) * 255 / max(1, softness)))) for v in range(256)]
        alpha = gray.point(lut)
    rgb = img.convert("RGB")
    if not keep_color:                                         # encre unie : couleur moyenne des traits
        ink = tuple(int(x) for x in ImageStat.Stat(rgb, mask=alpha.point(lambda v: 255 if v > 200 else 0)).mean[:3]) or (0, 0, 0)
        rgb = Image.new("RGB", rgb.size, ink)
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    if trim:
        box = alpha.point(lambda v: 255 if v > 10 else 0).getbbox()
        if box:
            pad = 4
            out = out.crop((max(0, box[0] - pad), max(0, box[1] - pad), min(out.width, box[2] + pad), min(out.height, box[3] + pad)))
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return buf.getvalue()
