"""Render every sample and tile them into a contact sheet, cropped to what the mat shows.
Usage: sheet.py out.png [--panel WxH] [--config FILE]
--panel 758x1024 and --config sky/config-pw2.json show a PW2."""
import glob
import json
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SKY = os.path.join(HERE, "..")
args = sys.argv[1:]
panel = args[args.index("--panel") + 1] if "--panel" in args else None
config = args[args.index("--config") + 1] if "--config" in args else os.path.join(SKY, "config.json")
out = args[0]
with open(config) as f:
    SAFE = tuple(json.load(f)["safe"])
# The panel is the PW4's canvas scaled; so is the crop
scale = int(panel.split("x")[1]) / 1448.0 if panel else 1.0
SAFE = tuple(round(v * scale) for v in SAFE)
label_font = ImageFont.truetype(os.path.join(SKY, "fonts", "IBMPlexSans-SemiBold.ttf"), 22)

tiles = []
for path in sorted(glob.glob(os.path.join(HERE, "*.json"))):
    name = os.path.basename(path)[:-5]
    png = "/tmp/sample_%s.png" % name
    cmd = [sys.executable, os.path.join(SKY, "sky.py"), "--sample", path, "--rotate", "0", "--out", png, "--config", config]
    if panel:
        cmd += ["--panel", panel]
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL)
    im = Image.open(png).crop(SAFE).convert("L")
    # Case name in a strip above the tile, never on top of the design
    framed = Image.new("L", (im.width, im.height + 34), 120)
    framed.paste(im, (0, 34))
    ImageDraw.Draw(framed).text((6, 8), name.replace("_", " "), fill=255, font=label_font)
    tiles.append(framed)

tw, th = tiles[0].size
cols = 2
sheet = Image.new("L", (cols * tw + (cols + 1) * 16, ((len(tiles) + 1) // cols) * (th + 16) + 16), 120)
for i, t in enumerate(tiles):
    sheet.paste(t, (16 + (i % cols) * (tw + 16), 16 + (i // cols) * (th + 16)))
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)  # out/ is gitignored, so a fresh clone has none
sheet.save(out)
print(out)
