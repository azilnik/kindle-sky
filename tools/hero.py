"""The README's hero: the sky frame on the kitchen counter, a day in 22 seconds, as a loop.
The ISS is due tonight, then crosses the dome with a Starlink train beside it; the full
moon late that night; the next morning's weather balloon climbing, then falling; and the
evening again. Renders come from the
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
from PIL import Image, ImageChops, ImageDraw, ImageFilter

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
INK = np.array([46, 44, 42], float)
# The mat window in the photo is wider than today's insert's: a `safe` of the same shape
SAFE = [16, 34, 1302, 1030]


def render(sample, t, days=0, balloon=True):
    """A sample at time t; `days` moves its weather balloon that many days on, with t, so
    the screens follow one another and what each says is next is what comes next."""
    with open(os.path.join(SAMPLES, sample + ".json")) as f:
        data = json.load(f)
    if not balloon:
        data.pop("balloon", None)
    b, d = data.get("balloon"), days * 86400
    if b and d:
        b["track"] = [[f[0] + d] + f[1:] for f in b["track"]]
        b["launched"] += d
    return sky.render(data, t + d)[0].convert("L").crop(SAFE)


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
    rgb = (INK + (PAPER - INK) * g) * shade[..., None] + panel_grain(w, h)[..., None]
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")


_grain = {}


def panel_grain(w, h):
    """E-ink's own surface: a faint mottle, a little uneven across the panel, the same in every
    frame because it's in the panel, not the camera. A perfectly even fill reads as pasted on."""
    if (w, h) not in _grain:
        rng = np.random.default_rng(3)
        blotch = Image.fromarray(rng.normal(128, 40, (h // 24, w // 24)).clip(0, 255).astype(np.uint8))
        blotch = np.asarray(blotch.resize((w, h), Image.BICUBIC), float) - 128
        fine = np.asarray(Image.fromarray(rng.normal(128, 40, (h // 2, w // 2)).clip(0, 255).astype(np.uint8))
                          .resize((w, h), Image.BILINEAR), float) - 128
        _grain[w, h] = blotch * 0.025 + fine * 0.02
    return _grain[w, h]


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
    # BOX, not LANCZOS: Lanczos rings, and a bright halo along the panel's edge gives it away
    warped = warped.resize((bw, bh), Image.BOX).filter(ImageFilter.GaussianBlur(0.45 * k))
    mask = Image.new("L", (bw * 4, bh * 4), 0)
    ImageDraw.Draw(mask).polygon([((x - x0) * 4, (y - y0) * 4) for x, y in quad], fill=255)
    mask = mask.resize((bw, bh), Image.BOX).filter(ImageFilter.GaussianBlur(0.3 * k))
    out = plate.copy()
    out.paste(Image.composite(warped, out.crop((x0, y0, x1, y1)), mask), (x0, y0))
    return out


def place(screen, plate):
    """At 2x then down, so the screen's edges are smooth, and softened like the photo."""
    big = composite(screen, plate.resize((plate.size[0] * 2, plate.size[1] * 2)), 2)
    return big.resize(plate.size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.35))


GHOST = 0.025


def change(old, new):
    """A new page as e-ink draws one, over three frames (120 ms, a panel's partial refresh):
    what's leaving goes dark first, then what's arriving comes up. Never both at once, so
    nothing is double-exposed, and no black-and-white flash: in a loop that plays every few
    seconds that pulls the eye from the sky itself. The old page then stays as a faint ghost
    (ghosted())."""
    erased = ImageChops.darker(old, new)
    return [Image.blend(old, erased, 0.6), erased, Image.blend(erased, new, 0.6)]


def ghosted(frames):
    """Every frame after a page change carries the page before it at GHOST, as a panel's
    partial refresh leaves it, until the next page; the opening carries the closing page's,
    so the loop wraps onto the very picture it left."""
    out, ghost, page, made = [], None, None, {}
    pages = [p for p, _, kind in frames if kind == "page"]
    ghost = pages[-2] if len(pages) > 1 else None
    for img, scene, kind in frames:
        if kind == "page" and page is not None and img is not page:
            ghost = page
        if kind == "page":
            page = img
        if ghost is not None:
            # The same blend object for a held picture, so callers can tell it hasn't changed
            key = (id(img), id(ghost))
            if key not in made:
                made[key] = Image.blend(img, ghost, GHOST)
            img = made[key]
        out.append((img, scene))
    return out


def partial(old, new):
    """A small update (the ISS a step on) redraws the same way, erase then draw."""
    return change(old, new)


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
    """The screen at every frame, FPS_MS apart, and which scene each frame belongs to. A
    Saturday evening into Sunday morning: the ISS due at 8:01, its pass, the full moon at
    10:30, the morning's weather balloon, and the loop back to the evening. Each screen's
    "Next" and "Up ahead" agree with the ones after it."""
    # The iss_soon sample at its own 7:25 pm: the ISS due at 8:01. Any later and a smaller
    # Starlink train at 7:38 takes the headline
    evening = 1790465100
    moon = 1790400600 + 21 * 3600         # the late_moon sample's Saturday, at 10:30 pm: the full moon
    # The sample's own evening balloon is left out: its data goes stale before the pass, and
    # it would vanish from the dome mid-scene
    first = render("iss_soon", evening, balloon=False)
    # From a minute before it rises to the moment it sets, every 20 s (the Kindle's every 15 s,
    # plugged in), 11 frames each
    rise, sets = 1790465100 + 34 * 60, pass_end("iss_soon", evening)
    scenes = [
        ("hold", [first], 95),
        ("change", [render("iss_soon", tt, balloon=False) for tt in range(rise, int(sets) + 1, 20)], 11),
        ("change", [render("late_moon", moon)], 85),
        # Friday's balloon from Buffalo, moved to Sunday morning: climbing, then falling. The
        # loop then wraps to Saturday evening, the one place the clock goes back
        ("change", [render("day", 1790339100, days=2)], 70),
        ("change", [render("balloon_burst", 1790341920, days=2)], 70),
    ]
    frames, last = [], None
    for n, (how, imgs, hold) in enumerate(scenes):
        for k, img in enumerate(imgs):
            if last is not None:
                between = change(last, img) if how == "change" and k == 0 else partial(last, img)
                frames += [(b, n, "between") for b in between]
            # A new page leaves a ghost; the pass's small steps redraw over the same page
            kind = "page" if k == 0 else "step"
            frames += [(img, n, kind)] * hold
            last = img
    if loop:
        # Back to the first picture, so the loop wraps onto the frame it started from
        frames += [(b, 0, "between") for b in change(last, first)] + [(first, 0, "page")]
    return ghosted(frames)


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
