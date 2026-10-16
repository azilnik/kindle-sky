"""Test pattern for measuring `safe`, the part of the screen a frame leaves visible.

Lines every 20 px, heavy and labeled every 100, in the 1448x1072 landscape canvas, turned
onto the panel like loop.py does. Labels say which axis they are (x300, y400), so a photo
of any strip of the screen can be read without seeing the rest.

With --safe it draws that box instead, to check a measurement: all four sides of the border
should be visible, right at the edge of the mat. The map runs to that box; text keeps 1 mm
(12 px, config.json "inset") further in by itself.

Coordinates are always the 1448x1072 canvas; --panel scales the picture for a smaller
Kindle the way loop.py does, so the numbers still mean the same thing.

Usage: grid.py ROTATE out.png [--safe X0,Y0,X1,Y1] [--panel WxH]
tools/grid.sh puts it on the Kindle."""
import argparse
import os

from PIL import Image, ImageDraw, ImageFont

W, H = 1448, 1072
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def font(size):
    return ImageFont.truetype(os.path.join(ROOT, "sky/fonts/IBMPlexSans-Bold.ttf"), size)


def notice(d, lines, size=30):
    """White box in the middle of the canvas; the edges are what gets measured.
    It covers whole grid cells, so no label is left half showing."""
    f = font(size)
    step = size + 14
    x0, y0, x1, y1 = 300, 400, 1100, 700
    d.rectangle((x0, y0, x1, y1), fill=255, outline=0, width=3)
    top = (y0 + y1 - step * len(lines)) // 2
    for i, s in enumerate(lines):
        w = d.textbbox((0, 0), s, font=f)[2]
        d.text(((x0 + x1 - w) // 2, top + i * step), s, font=f, fill=0)


def grid():
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    for x in range(0, W, 20):
        d.line((x, 0, x, H), fill=0 if x % 100 == 0 else 170, width=3 if x % 100 == 0 else 1)
    for y in range(0, H, 20):
        d.line((0, y, W, y), fill=0 if y % 100 == 0 else 170, width=3 if y % 100 == 0 else 1)
    f = font(22)
    # Repeated so any visible strip carries its numbers; each on a white patch so the
    # thin lines don't run through the digits
    for x in range(100, W, 100):
        for y in range(28, H, 200):
            d.rectangle((x + 3, y, x + 78, y + 28), fill=255)
            d.text((x + 6, y), "x%d" % x, font=f, fill=0)
    for y in range(100, H, 100):
        for x in range(112, W, 200):
            d.rectangle((x - 3, y + 3, x + 72, y + 31), fill=255)
            d.text((x, y + 3), "y%d" % y, font=f, fill=0)
    notice(d, ["TEST PATTERN  1448 x 1072",
               "Heavy lines every 100 px, thin lines every 20 px",
               "Read the first thing visible at each edge:",
               "safe = [left x, top y, right x, bottom y]"])
    return img


def check(safe):
    x0, y0, x1, y1 = safe
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    d.rectangle((x0, y0, x1 - 1, y1 - 1), outline=0, width=8)
    f = font(26)
    for (x, y, label, ax, ay) in ((x0, y0, "x%d y%d" % (x0, y0), 0, 0), (x1, y0, "x%d y%d" % (x1, y0), 1, 0),
                                  (x0, y1, "x%d y%d" % (x0, y1), 0, 1), (x1, y1, "x%d y%d" % (x1, y1), 1, 1)):
        w = d.textbbox((0, 0), label, font=f)[2]
        d.text((x + 24 if not ax else x - 24 - w, y + 20 if not ay else y - 56), label, font=f, fill=0)
    notice(d, ["SAFE AREA CHECK", "safe = [%d, %d, %d, %d]" % tuple(safe),
               "All four sides of the black border should be",
               "visible, right at the edge of the mat.",
               "A side you can't see is hidden: move it inward."])
    return img


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("rotate", type=int, choices=(0, 90, 180, 270), help="same as `rotate` in config.json")
    ap.add_argument("out")
    ap.add_argument("--safe", help="X0,Y0,X1,Y1: draw this box instead of the grid")
    ap.add_argument("--panel", help="the Kindle's portrait panel, WxH (758x1024 for a PW2)")
    args = ap.parse_args()
    img = check([int(v) for v in args.safe.split(",")]) if args.safe else grid()
    if args.panel:
        pw, ph = (int(v) for v in args.panel.split("x"))
        if (ph, pw) != img.size:
            img = img.resize((ph, pw), Image.LANCZOS)
    if args.rotate:
        img = img.transpose({90: Image.ROTATE_270, 180: Image.ROTATE_180, 270: Image.ROTATE_90}[args.rotate])
    img.save(args.out)
    print(args.out)


if __name__ == "__main__":
    main()
