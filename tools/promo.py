"""A square video of the README's hero for social feeds: the same day on the frame as
tools/hero.py, with a slow camera. It opens on the whole frame, eases in on the screen as
the ISS crosses, rests on the Moon and pulls back out for the weather balloon.

The screen is set into the photo at the size it's shown, so it stays sharp up close; the
kitchen behind the frame is softened the way a lens would, and the picture gets a little
grain and a vignette, like video from a phone.

Usage: uv run --python 3.12 --with pillow --with numpy --with requests python tools/promo.py [out.mp4]
Needs ffmpeg. 1080x1080, 25 fps, no sound: feeds play muted.
"""

import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hero  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(hero.ROOT, "out", "promo.mp4")
SIZE = 1080
K = 3.3                    # the photo's scale for the composite: 1080 px over the closest view
FRAME = (80, 55, 722, 522)  # the picture frame in the photo, in focus; behind it isn't
# The camera, as a square in the photo's pixels (center x, center y, side), at the end of each
# scene: in on the screen through the pass, a little closer on the Moon, back out for the
# balloon. Never so close that the mat goes: then it stops looking like a frame
WIDE = (400, 300, 600)
KEYS = [WIDE, (403, 298, 540), (404, 294, 430), (404, 294, 415), WIDE]


def ease(u):
    return u * u * (3 - 2 * u)


def camera(i, bounds):
    """Where the camera is at frame i: each scene's move eases from the last key to its own."""
    for n, (a, b) in enumerate(bounds):
        if a <= i < b:
            u = ease((i - a) / max(1, b - a - 1))
            return tuple(s + (e - s) * u for s, e in zip(KEYS[n], KEYS[n + 1]))
    return KEYS[-1]


def lens(plate):
    """The photo at K times its size: the frame as it is, the kitchen behind it softer."""
    big = plate.resize((round(plate.size[0] * K), round(plate.size[1] * K)), Image.LANCZOS)
    soft = big.filter(ImageFilter.GaussianBlur(7))
    mask = Image.new("L", big.size, 0)
    ImageDraw.Draw(mask).rectangle([v * K for v in FRAME], fill=255)
    return Image.composite(big.filter(ImageFilter.GaussianBlur(0.8)), soft, mask.filter(ImageFilter.GaussianBlur(40)))


def finish(img, rng):
    """Vignette and grain."""
    a = np.asarray(img, float)
    yy, xx = np.mgrid[0:SIZE, 0:SIZE] / (SIZE / 2.0) - 1
    a *= (1 - 0.18 * np.clip(xx * xx + yy * yy - 0.3, 0, None))[..., None]
    a += rng.normal(0, 2.2, (SIZE, SIZE, 1))
    return np.clip(a, 0, 255).astype(np.uint8)


def main():
    plate = lens(hero.setup())
    frames = hero.timeline(loop=False)
    # Where each scene starts and ends, in frames; the camera moves once per scene
    bounds, start = [], 0
    for i in range(1, len(frames) + 1):
        if i == len(frames) or frames[i][1] != frames[i - 1][1]:
            bounds.append((start, i))
            start = i
    # The balloon's two pictures are one scene for the camera: the pull back runs through both
    bounds = bounds[:3] + [(bounds[3][0], len(frames))]
    os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", "%dx%d" % (SIZE, SIZE), "-r", str(1000 // hero.FPS_MS), "-i", "-",
                           "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p",
                           "-movflags", "+faststart", OUT], stdin=subprocess.PIPE)
    rng = np.random.default_rng(7)
    shown, layer = None, None
    for i, (screen, _) in enumerate(frames):
        if screen is not shown:
            shown, layer = screen, hero.composite(screen, plate, K)
        cx, cy, side = camera(i, bounds)
        box = [(cx - side / 2) * K, (cy - side / 2) * K, (cx + side / 2) * K, (cy + side / 2) * K]
        view = layer.transform((SIZE, SIZE), Image.EXTENT, box, Image.BICUBIC)
        ff.stdin.write(finish(view, rng).tobytes())
    ff.stdin.close()
    ff.wait()
    print(OUT, len(frames), "frames, %.1f s" % (len(frames) * hero.FPS_MS / 1000.0))


if __name__ == "__main__":
    main()
