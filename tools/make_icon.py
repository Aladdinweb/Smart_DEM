"""Génère assets/smart_dem.ico (+ PNG 256) : carré arrondi vert dégradé, croix médicale blanche, anneau. Remplaçable par n'importe quel .ico."""
import os
from PIL import Image, ImageDraw

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
grad = Image.new("RGBA", (S, S))
for y in range(S):
    t = y / S
    ImageDraw.Draw(grad).line((0, y, S, y), fill=(int(0 + 8 * t), int(110 + 50 * (1 - t)), int(70 + 30 * (1 - t)), 255))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle((40, 40, S - 40, S - 40), radius=220, fill=255)
img.paste(grad, (0, 0), mask)
d = ImageDraw.Draw(img)
d.ellipse((150, 150, S - 150, S - 150), outline=(255, 255, 255, 120), width=26)
d.rounded_rectangle((S // 2 - 70, 250, S // 2 + 70, S - 250), radius=40, fill="white")
d.rounded_rectangle((250, S // 2 - 70, S - 250, S // 2 + 70), radius=40, fill="white")
d.ellipse((S - 330, S - 330, S - 190, S - 190), fill=(210, 16, 52, 255))              # pastille rouge (clin d'œil aux couleurs nationales)
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
os.makedirs(out, exist_ok=True)
img.resize((256, 256), Image.LANCZOS).save(os.path.join(out, "smart_dem_256.png"))
img.save(os.path.join(out, "smart_dem.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icône générée")
