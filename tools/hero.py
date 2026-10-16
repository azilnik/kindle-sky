"""The README's hero: the sky frame on the kitchen counter, a day in 25 seconds. The ISS is
due tonight, then crosses the dome with a Starlink train beside it; the Harvest Moon after
midnight; the morning's weather balloon climbing, then falling. E-ink flashes between them. Renders come from the samples, set into the photo of the frame
(docs/images/frame.jpg) where its screen is, in the panel's own grays.

Usage: uv run --python 3.12 --with pillow --with numpy --with requests python tools/hero.py [out.gif]
Takes a few minutes: every frame is a real render.
"""

import json
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SAMPLES = os.path.join(ROOT, "sky", "samples")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "images", "hero.gif")
FPS_MS = 40
# The screen in the photo, clockwise from top left: the camera sits a little to the left
QUAD = [(227, 153), (581, 160), (574, 435), (230, 421)]
# The photo's e-ink: its white is a cool gray and its black a warm dark gray
PAPER = np.array([158, 166, 167], float)
INK = np.array([50, 45, 41], float)
# The mat window in the photo is wider than today's insert's: a `safe` of the same shape
SAFE = [16, 34, 1302, 1030]


def render(sample, t, cfg):
    out = os.path.join(TMP, "%s-%d.png" % (sample, t))
    if not os.path.exists(out):
        subprocess.check_call([sys.executable, os.path.join(ROOT, "sky", "sky.py"), "--sample",
                               os.path.join(SAMPLES, sample + ".json"), "--time", str(t), "--rotate", "0",
                               "--config", cfg, "--out", out], stdout=subprocess.DEVNULL)
    return Image.open(out).convert("L").crop(SAFE)


def coeffs(src, dst):
    """PERSPECTIVE coefficients taking points in dst back to src, for Image.transform."""
    rows, rhs = [], []
    for (x, y), (u, v) in zip(dst, src):
        rows += [[x, y, 1, 0, 0, 0, -u * x, -u * y], [0, 0, 0, x, y, 1, -v * x, -v * y]]
        rhs += [u, v]
    return np.linalg.solve(np.array(rows, float), np.array(rhs, float))


def place(screen, plate):
    """The render, tinted to e-ink and warped onto the screen in the photo, at 2x then down
    so its edges are smooth."""
    g = np.asarray(screen, float)[..., None] / 255.0
    # The panel's light falls off toward the mat's shadowed top and left
    h, w = screen.size[1], screen.size[0]
    yy, xx = np.mgrid[0:h, 0:w]
    shade = 1 - 0.10 * np.clip(1 - np.minimum(xx / (0.03 * w), yy / (0.04 * h)), 0, 1) - 0.04 * yy / h
    rgb = (INK + (PAPER - INK) * g) * shade[..., None]
    tinted = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")
    big = plate.size[0] * 2, plate.size[1] * 2
    quad = [(x * 2, y * 2) for x, y in QUAD]
    c = coeffs([(0, 0), (w, 0), (w, h), (0, h)], quad)
    warped = tinted.transform(big, Image.PERSPECTIVE, tuple(c), Image.BICUBIC)
    mask = Image.new("L", (w, h), 255).transform(big, Image.PERSPECTIVE, tuple(c), Image.BICUBIC)
    layer = Image.composite(warped, plate.resize(big), mask).resize(plate.size, Image.LANCZOS)
    return layer.filter(ImageFilter.GaussianBlur(0.35))


def flash(old, new):
    """A full refresh as the panel does it: the old picture inverts, black, white, then the new."""
    inv = Image.eval(old, lambda v: 255 - v)
    return [inv, inv, Image.new("L", old.size, 0), Image.new("L", old.size, 0),
            Image.new("L", old.size, 255), Image.new("L", old.size, 255), Image.new("L", old.size, 0),
            Image.blend(Image.new("L", old.size, 0), new, 0.5), new, new, new]


def partial(old, new, n=4):
    """A partial update: the changed parts settle over a few frames."""
    return [Image.blend(old, new, (i + 1) / n) for i in range(n)]


def main():
    global TMP
    TMP = tempfile.mkdtemp()
    with open(os.path.join(ROOT, "sky", "config.json")) as f:
        cfg = dict(json.load(f), safe=SAFE)
    cfg_path = os.path.join(TMP, "config.json")
    with open(cfg_path, "w") as f:
        json.dump(cfg, f)
    plate = Image.open(os.path.join(ROOT, "docs", "images", "frame.jpg")).convert("RGB")

    evening = 1790465100                  # the iss_soon sample: 7:25 pm, ISS overhead at 8:01
    moon = 1790400600                     # the late_moon sample: 1:30 am, the Harvest Moon
    scenes = [
        ("hold", [render("iss_soon", evening, cfg_path)], 100),
        # Plugged in, a pass redraws every 15 seconds; here every 20 of them, 11 frames each
        ("flash", [render("iss_soon", evening + 34 * 60 + 20 * i, cfg_path) for i in range(19)], 11),
        ("flash", [render("late_moon", moon, cfg_path)], 70),
        # The morning's weather balloon from Buffalo, climbing, then falling after it bursts
        ("flash", [render("day", 1790339100, cfg_path)], 70),
        ("partial", [render("balloon_burst", 1790341920, cfg_path)], 70),
    ]
    screens, last = [], None
    for how, imgs, hold in scenes:
        for k, img in enumerate(imgs):
            if last is not None:
                screens += flash(last, img) if how == "flash" and k == 0 else partial(last, img)
            screens += [img] * hold
            last = img
    # Back to the first picture, so the loop has no seam
    first = scenes[0][1][0]
    screens += flash(last, first)
    frames, cache = [], {}
    for s in screens:
        key = s.tobytes().__hash__()
        if key not in cache:
            cache[key] = place(s, plate).quantize(colors=128, method=Image.MEDIANCUT, dither=Image.NONE)
        frames.append(cache[key])
    os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
    frames[0].save(OUT, save_all=True, append_images=frames[1:], duration=FPS_MS, loop=0, optimize=True)
    print(OUT, len(frames), "frames, %.1f s" % (len(frames) * FPS_MS / 1000.0))


if __name__ == "__main__":
    main()
