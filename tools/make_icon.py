"""Régénère assets/smart_dem.ico (7 tailles, 16 à 256 px) à partir de assets/smart_dem_256.png (icône « SMART DEM SYSTEM », fournie).
Pour changer d'icône : remplacez assets/smart_dem_256.png (PNG carré à coins transparents) puis lancez : python tools/make_icon.py"""
import os
from PIL import Image

out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
img = Image.open(os.path.join(out, "smart_dem_256.png")).convert("RGBA").resize((256, 256), Image.LANCZOS)
img.save(os.path.join(out, "smart_dem.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("assets/smart_dem.ico régénéré")
