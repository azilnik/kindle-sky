"""A square video of the README's hero for social feeds: the same day on the frame as
tools/hero.py, as a seamless loop. The camera barely breathes: a few percent closer while
the ISS crosses, a slow drift and a hand's unsteadiness, with the kitchen behind moving less
than the frame. All of it is periodic over the loop, so its last frame leads into its first
with no jump in picture or motion.

The screen is set into the photo at the size it's shown, so it stays sharp up close; the
kitchen behind the frame is softened the way a lens would, and the picture gets a little
grain and a vignette, like video from a phone.

Usage: uv run --python 3.12 --with pillow --with numpy --with requests python tools/promo.py [out.mp4]
Needs ffmpeg. 1080x1080, 25 fps, no sound: feeds play muted.
"""

import math
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
# The camera, as a square in the photo's pixels. Its widest leaves the photo a few pixels to
# spare for the hand's wobble; at its closest, during the ISS pass, under a tenth tighter. Any
# closer and it reads as a zoom
WIDEST, CLOSEST = 588, 548
TARGET = (402, 296)        # the screen's middle, as near as the photo's edges allow
DRIFT = 5                  # side to side, once over the loop
# The kitchen is a few feet behind the frame: it moves less than the frame as the camera
# does, which is what makes a still photo read as filmed
DEPTH = 0.55


def cycle(i, n, *waves):
    """A sum of (amplitude, cycles per loop, phase) sines: periodic over n frames, so the loop's
    last frame flows into its first."""
    return sum(a * math.sin(2 * math.pi * c * i / n + ph) for a, c, ph in waves)


def camera(i, n, closest_at):
    """Where the camera is at frame i of n, and its tilt in degrees: a slow breath in for the
    pass and out again, a drift, and a hand's small unsteadiness, all periodic over the loop."""
    side = (WIDEST + CLOSEST) / 2 - (WIDEST - CLOSEST) / 2 * math.cos(2 * math.pi * (i - closest_at) / n)
    # Slow sway, and a gimbal's faint tremor at 1 to 3 Hz on top: a camera with nothing in its
    # motion faster than a few seconds reads as virtual
    hx = cycle(i, n, (0.9, 3, 0.4), (0.45, 7, 1.3), (0.2, 13, 2.1), (0.12, 27, 0.5), (0.08, 43, 2.9), (0.05, 61, 1.7))
    hy = cycle(i, n, (0.7, 4, 2.2), (0.35, 9, 0.2), (0.15, 15, 1.0), (0.10, 31, 1.1), (0.07, 47, 0.3), (0.05, 67, 2.4))
    tilt = cycle(i, n, (0.10, 2, 0.7), (0.05, 5, 2.4), (0.008, 37, 0.9), (0.005, 53, 2.0))
    cx = TARGET[0] + DRIFT * math.sin(2 * math.pi * i / n) + hx
    cy = min(max(TARGET[1] + hy, side / 2 + 3), 600 - side / 2 - 3)
    return cx, cy, side, tilt


def view(layer, cx, cy, side, tilt):
    """The camera's square of the photo, turned by `tilt`, at SIZE."""
    a = math.radians(tilt)
    h = side / 2 * K
    corners = []
    for ux, uy in ((-1, -1), (-1, 1), (1, 1), (1, -1)):  # QUAD order: UL, LL, LR, UR
        corners += [cx * K + h * (ux * math.cos(a) - uy * math.sin(a)), cy * K + h * (ux * math.sin(a) + uy * math.cos(a))]
    return layer.transform((SIZE, SIZE), Image.QUAD, corners, Image.BICUBIC)


def lens(plate):
    """The photo at K times its size, in focus where the frame is and soft behind it, and the
    mask between them."""
    big = plate.resize((round(plate.size[0] * K), round(plate.size[1] * K)), Image.LANCZOS)
    mask = Image.new("L", big.size, 0)
    ImageDraw.Draw(mask).rectangle([v * K for v in FRAME], fill=255)
    return big.filter(ImageFilter.GaussianBlur(0.8)), big.filter(ImageFilter.GaussianBlur(7)), \
        mask.filter(ImageFilter.GaussianBlur(40))


# The room's light through the day the screen tells, by scene: dusk for the ISS, lamps late
# at night for the Moon, daylight for the morning's balloon. Its own e-ink screen, lit by the
# same room, follows
ROOM = [0.95, 0.93, 0.89, 1.0, 1.0]


def room_light(scenes, n):
    """Light per frame: each scene's level, smoothed over a few seconds around the loop,
    so it drifts the way daylight does and the last frame meets the first."""
    raw = np.array([ROOM[s] for s in scenes])
    k = np.exp(-0.5 * (np.arange(-120, 121) / 40.0) ** 2)
    k /= k.sum()
    padded = np.concatenate([raw[-120:], raw, raw[:120]])
    return np.convolve(padded, k, mode="valid")[:n]


def finish(img, rng, light=1.0):
    """Room light, vignette and grain. Dimmer is warmer: lamps, not daylight."""
    a = np.asarray(img, float)
    warm = (1 - light) / (1 - min(ROOM))
    a *= light * np.array([1 + 0.025 * warm, 1.0, 1 - 0.035 * warm])
    yy, xx = np.mgrid[0:SIZE, 0:SIZE] / (SIZE / 2.0) - 1
    a *= (1 - 0.18 * np.clip(xx * xx + yy * yy - 0.3, 0, None))[..., None]
    a += rng.normal(0, 2.2, (SIZE, SIZE, 1))
    return np.clip(a, 0, 255).astype(np.uint8)


def main():
    sharp, soft, mask = lens(hero.setup())
    frames = hero.timeline()
    n = len(frames)
    # The camera is closest in the middle of the pass, the timeline's second scene
    pass_frames = [i for i, (_, scene) in enumerate(frames) if scene == 1]
    closest_at = (pass_frames[0] + pass_frames[-1]) / 2
    light = room_light([scene for _, scene in frames], n)
    os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
    # One keyframe for the whole loop, no B-frames and every frame at the same quality, with
    # x264 told to keep the grain: otherwise grain and sharpness pulse with the frame types
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", "%dx%d" % (SIZE, SIZE), "-r", str(1000 // hero.FPS_MS), "-i", "-",
                           "-c:v", "libx264", "-preset", "slow", "-tune", "grain", "-crf", "20",
                           "-g", str(n + 1), "-x264-params", "scenecut=0:bframes=0:ipratio=1.0", "-pix_fmt", "yuv420p",
                           "-movflags", "+faststart", OUT], stdin=subprocess.PIPE)
    rng = np.random.default_rng(7)
    shown, layer = None, None
    mid = (WIDEST + CLOSEST) / 2
    for i, (screen, _) in enumerate(frames):
        if screen is not shown:
            shown, layer = screen, hero.composite(screen, sharp, K)
        cx, cy, side, tilt = camera(i, n, closest_at)
        near = view(layer, cx, cy, side, tilt)
        # Behind the frame, every move of the camera's is smaller
        far = view(soft, TARGET[0] + (cx - TARGET[0]) * DEPTH, TARGET[1] + (cy - TARGET[1]) * DEPTH,
                   mid + (side - mid) * DEPTH, tilt)
        ff.stdin.write(finish(Image.composite(near, far, view(mask, cx, cy, side, tilt)), rng, light[i]).tobytes())
    ff.stdin.close()
    ff.wait()
    print(OUT, len(frames), "frames, %.1f s" % (len(frames) * hero.FPS_MS / 1000.0))


if __name__ == "__main__":
    main()
