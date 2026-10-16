"""The README's hero: the sky frame on the kitchen counter, a day in 25 seconds. The ISS is
due tonight, then crosses the dome with a Starlink train beside it; the Harvest Moon after
midnight; the morning's weather balloon climbing, then falling. Renders come from the
samples, set into the photo of the frame (docs/images/frame.jpg) where its screen is, in the
panel's own grays.

Usage: uv run --python 3.12 --with pillow --with numpy --with requests python tools/hero.py [out.gif]
Every frame is a real render, in order in one process as on the Kindle: a pass is found once,
before it starts, and its numbers hold still while it crosses.
"""

import argparse
import json
import os
import sys
import tempfile

import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "sky"))
import base  # noqa: E402

import sky  # noqa: E402

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


def render(sample, t):
    with open(os.path.join(SAMPLES, sample + ".json")) as f:
        data = json.load(f)
    return sky.render(data, t)[0].convert("L").crop(SAFE)


def pass_end(sample, t):
    """When the ISS pass that's coming at `t` sets."""
    with open(os.path.join(SAMPLES, sample + ".json")) as f:
        return sky.build(json.load(f), t)["pass"]["set"]


def coeffs(src, dst):
    """PERSPECTIVE coefficients taking points in dst back to src, for Image.transform."""
    rows, rhs = [], []
    for (x, y), (u, v) in zip(dst, src):
        rows += [[x, y, 1, 0, 0, 0, -u * x, -u * y], [0, 0, 0, x, y, 1, -v * x, -v * y]]
        rhs += [u, v]
    return np.linalg.solve(np.array(rows, float), np.array(rhs, float))


def tint(screen):
    """The render in the photo's e-ink grays, its light falling off toward the mat's shadowed
    top and left."""
    g = np.asarray(screen, float)[..., None] / 255.0
    h, w = screen.size[1], screen.size[0]
    yy, xx = np.mgrid[0:h, 0:w]
    shade = 1 - 0.10 * np.clip(1 - np.minimum(xx / (0.03 * w), yy / (0.04 * h)), 0, 1) - 0.04 * yy / h
    rgb = (INK + (PAPER - INK) * g) * shade[..., None]
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")


def composite(screen, plate, k):
    """The tinted render warped onto the screen in the photo, with the photo `k` times its size
    (pass it already scaled): the screen stays sharp however large the photo is drawn."""
    tinted = tint(screen)
    w, h = tinted.size
    c = coeffs([(0, 0), (w, 0), (w, h), (0, h)], [(x * k, y * k) for x, y in QUAD])
    warped = tinted.transform(plate.size, Image.PERSPECTIVE, tuple(c), Image.BICUBIC)
    mask = Image.new("L", (w, h), 255).transform(plate.size, Image.PERSPECTIVE, tuple(c), Image.BICUBIC)
    return Image.composite(warped, plate, mask)


def place(screen, plate):
    """At 2x then down, so the screen's edges are smooth, and softened like the photo."""
    big = composite(screen, plate.resize((plate.size[0] * 2, plate.size[1] * 2)), 2)
    return big.resize(plate.size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.35))


def change(old, new):
    """A new scene fades in over a third of a second. The panel really flashes black and white
    here, but in a loop that plays every few seconds it pulls the eye from the sky itself."""
    return [Image.blend(old, new, (i + 1) / 9.0) for i in range(8)]


def partial(old, new, n=4):
    """A partial update: the changed parts settle over a few frames."""
    return [Image.blend(old, new, (i + 1) / n) for i in range(n)]


def setup():
    with open(os.path.join(ROOT, "sky", "config.json")) as f:
        cfg = dict(json.load(f), safe=SAFE)
    cfg_path = os.path.join(tempfile.mkdtemp(), "config.json")
    with open(cfg_path, "w") as f:
        json.dump(cfg, f)
    base.load_config(argparse.Namespace(config=cfg_path, heading=None, rotate=0))
    sky.layout()
    return Image.open(os.path.join(ROOT, "docs", "images", "frame.jpg")).convert("RGB")


def timeline(loop=True):
    """The screen at every frame, FPS_MS apart, and which scene each frame belongs to."""
    evening = 1790465100                  # the iss_soon sample: 7:25 pm, ISS overhead at 8:01
    moon = 1790400600                     # the late_moon sample: 1:30 am, the Harvest Moon
    first = render("iss_soon", evening)
    # From a minute before it rises to the moment it sets, every 20 s (the Kindle's every 15 s,
    # plugged in), 11 frames each
    rise, sets = evening + 34 * 60, pass_end("iss_soon", evening)
    scenes = [
        ("hold", [first], 100),
        ("change", [render("iss_soon", tt) for tt in range(rise, int(sets) + 1, 20)], 11),
        ("change", [render("late_moon", moon)], 70),
        # The morning's weather balloon from Buffalo, climbing, then falling after it bursts
        ("change", [render("day", 1790339100)], 70),
        ("partial", [render("balloon_burst", 1790341920)], 70),
    ]
    screens, last = [], None
    for n, (how, imgs, hold) in enumerate(scenes):
        for k, img in enumerate(imgs):
            if last is not None:
                screens += [(s, n) for s in (change(last, img) if how == "change" and k == 0 else partial(last, img))]
            screens += [(img, n)] * hold
            last = img
    if loop:
        # Back to the first picture, so the loop has no seam
        screens += [(s, 0) for s in change(last, first)]
    return screens


def main():
    plate = setup()
    screens = [s for s, _ in timeline()]
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
