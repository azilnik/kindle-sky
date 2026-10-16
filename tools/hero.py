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
from PIL import Image, ImageDraw, ImageFilter

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
    """The render in the photo's e-ink grays, with the shadow the mat's cut edge throws on the
    panel: deepest along the top and left, away from the window's light, and a trace at the
    other edges."""
    g = np.asarray(screen, float)[..., None] / 255.0
    h, w = screen.size[1], screen.size[0]
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    reach = 0.022 * w
    near = np.exp(-xx / reach) * 0.9 + np.exp(-yy / reach)
    far = np.exp(-(w - 1 - xx) / reach) + np.exp(-(h - 1 - yy) / reach)
    shade = 1 - 0.22 * np.clip(near, 0, 1) - 0.06 * np.clip(far, 0, 1) - 0.04 * yy / h
    rgb = (INK + (PAPER - INK) * g) * shade[..., None]
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")


def composite(screen, plate, k, ss=2):
    """The tinted render set onto the screen in the photo, with the photo `k` times its size
    (pass it already scaled), so the screen stays sharp however large the photo is drawn.
    Warped at `ss` times and brought down, so its lines and letters are smooth, inside an
    antialiased edge feathered a touch, as a lens sees the edge of the mat's window."""
    pad = 8
    # Edge pixels repeated outward: the feathered edge blends into the panel's own gray,
    # never into black
    tinted = Image.fromarray(np.pad(np.asarray(tint(screen)), ((pad, pad), (pad, pad), (0, 0)), mode="edge"))
    w, h = screen.size
    quad = [(x * k, y * k) for x, y in QUAD]
    x0, y0 = int(min(x for x, _ in quad)) - 4, int(min(y for _, y in quad)) - 4
    x1, y1 = int(max(x for x, _ in quad)) + 5, int(max(y for _, y in quad)) + 5
    bw, bh = x1 - x0, y1 - y0
    # The quad pushed out by the padding, in the same perspective, so the pad lands past the edge
    inner = coeffs([(pad, pad), (w + pad, pad), (w + pad, h + pad), (pad, h + pad)],
                   [((x - x0) * ss, (y - y0) * ss) for x, y in quad])
    warped = tinted.transform((bw * ss, bh * ss), Image.PERSPECTIVE, tuple(inner), Image.BICUBIC)
    # As soft as the photo around it at this size: a screen sharper than its own frame reads
    # as pasted on
    warped = warped.resize((bw, bh), Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.3 * k))
    mask = Image.new("L", (bw * 4, bh * 4), 0)
    ImageDraw.Draw(mask).polygon([((x - x0) * 4, (y - y0) * 4) for x, y in quad], fill=255)
    mask = mask.resize((bw, bh), Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.3 * k))
    out = plate.copy()
    out.paste(Image.composite(warped, out.crop((x0, y0, x1, y1)), mask), (x0, y0))
    return out


def place(screen, plate):
    """At 2x then down, so the screen's edges are smooth, and softened like the photo."""
    big = composite(screen, plate.resize((plate.size[0] * 2, plate.size[1] * 2)), 2)
    return big.resize(plate.size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.35))


def change(old, new):
    """A new scene fades in over a third of a second. The panel really flashes black and white
    here, but in a loop that plays every few seconds it pulls the eye from the sky itself."""
    return [Image.blend(old, new, (i + 1) / 9.0) for i in range(8)]


def partial(old, new):
    """A partial update snaps, as the panel's does: blended, a moving mark and its label
    show twice for a moment."""
    return []


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
