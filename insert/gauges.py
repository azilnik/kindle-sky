"""Fit tests for the PW2 build, on one plate.

Size gauges for the Kindle: bars with a stop at each end, a fixed distance apart.

Lay the Kindle face down across a bar: it drops between the stops of every bar longer than it
and sits on top of the shorter ones. The shortest bar it drops into, without play, is its size.
The stops are 7 mm tall, so they meet the edge wherever it is widest. Notches at one end
count off the bars: one notch for the shortest.

Panel tray: the solar panel drops face up into a pocket, its junction box through a hole near
one long edge and its cable out a slot in that edge, as the backing will hold it. Turn the
panel end for end if its box sits at the other edge.
Run:  uv run --python 3.12 --with manifold3d --with numpy --with trimesh --with networkx \\
          --with lxml python gauges.py
"""

import os

from insert import HERE, box, export

LENGTHS = (168.0, 168.5, 169.0, 169.5)
WIDTHS = (116.5, 117.0, 117.5)
BAR_W, BAR_T = 8.0, 1.6
STOP_L, STOP_H = 4.0, 7.0
# Solar panel, measured from a photo: outline, and the raised pad around its junction box,
# which sits 3.6 mm from one long edge, centered along the length
PANEL = (148.8, 44.6)     # length includes a clear laminate rim at each end
PAD = (35.2, 27.7)
PAD_EDGE = 3.7
CABLE_W = 5.5          # strain relief where the cable leaves the box sideways
FIT = 0.25


def bar(inner, marks):
    total = inner + 2 * STOP_L
    g = box(total, BAR_W, BAR_T)
    for s in (-1, 1):
        g = g + box(STOP_L, BAR_W, STOP_H, cx=s * (inner + STOP_L) / 2)
    for k in range(marks):
        g = g - box(1.2, 2.5, BAR_T + 0.1, cx=-inner / 2 + 4 + k * 2.5, cy=BAR_W / 2 - 1.0, z0=-0.05)
    return g


def tray():
    pl, pw = PANEL[0] + 2 * FIT, PANEL[1] + 2 * FIT
    rim, floor, wall = 3.0, 1.2, 1.6
    g = box(pl + 2 * wall, pw + 2 * wall, floor + wall)
    g = g - box(pl, pw, 10, z0=floor)                              # the panel's pocket
    g = g - box(pl - 2 * rim, pw - 2 * rim, 10, z0=-1)             # open floor inside a rim
    g = g + box(PAD[0] + 12, pw, floor)                            # a bridge to carry the box hole
    cy = pw / 2 - PAD_EDGE - PAD[1] / 2
    g = g - box(PAD[0] + 2 * FIT * 2, PAD[1] + 2 * FIT * 2, 10, cy=cy, z0=-1)
    g = g - box(CABLE_W, PAD_EDGE + wall + 2, 10, cy=pw / 2 - PAD_EDGE / 2 + 1, z0=-1)
    return g


def plate():
    g = None
    rows = [(v, i + 1) for i, v in enumerate(LENGTHS)] + [(v, i + 1) for i, v in enumerate(WIDTHS)]
    for row, (inner, marks) in enumerate(rows):
        piece = bar(inner, marks).translate((0, row * (BAR_W + 4), 0))
        g = piece if g is None else g + piece
    t = tray()
    return g + t.translate((0, len(rows) * (BAR_W + 4) + PANEL[1] / 2 + 4, 0))


if __name__ == "__main__":
    mesh = export(plate(), os.path.join(HERE, "test-gauges"))
    b = mesh.bounds[1] - mesh.bounds[0]
    print("test-gauges: %.0f x %.0f x %.1f mm, %.1f cm3, watertight %s" % (
        b[0], b[1], b[2], mesh.volume / 1000, mesh.is_watertight))
    print("lengths", LENGTHS, "widths", WIDTHS, "panel", PANEL)
