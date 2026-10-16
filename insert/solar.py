"""Solar backing for a framed Kindle on a windowsill: the back plate with a closed shell behind it.

A small USB solar panel faces the window at TILT from the horizontal, sitting in a niche on the
shell's sloped face: a 3 mm rim behind it, as in the printed tray, a lip over its top edge, a
ledge under its bottom edge and stops at its ends. The face stands STANDOFF clear of the plate,
so the junction box (toward the panel's lower edge) and its cable have room behind it to bend.
The shell is closed: the plate, a top wall, the face, an angled underside and two end walls.
The cable runs inside to the port end, where the Kindle's right-angle adapter plug comes
straight back through the plate into the same space, so no cable shows.
The plate holds itself in the frame with leaf-spring fingers, as insert.py describes.
Printed standing on its port end: every wall is vertical and the openings are peaked. Use
supports from the build plate only: the plate stays inside the rebate, so its bottom edge
starts 2 mm above the bed, and the cable slot's end bridges 38 mm.

Coordinates are insert.py's: x along the frame (0 at its center, + away from the port),
y up, z back from the mat's front face. The frame's back edge is at z = depth.
Run:  uv run --python 3.12 --with manifold3d --with numpy --with trimesh --with networkx \\
          --with lxml python solar.py [pw2]
"""

import math
import os
import sys

import numpy as np
from manifold3d import CrossSection, JoinType, Manifold

from insert import FRAMES, HERE, KINDLES, P, box, export, fingers, layout

TILT = 60.0              # panel from horizontal: 55 is best over a year in Toronto, 65 in winter
PANEL = (148.8, 44.6)    # length, width; fits the printed tray
PANEL_T = 2.5            # MEASURE: the panel's thickness sets the lip's groove
FIT = 0.25
LIP = 2.0                # how far the top lip covers the panel
TRAVEL = 2.5             # how far the panel slides up to clear the ledge going in
LEDGE = 2.0
LIP_T = 1.4
WALL = 1.6
END = 2.0
END_PORT = 1.5           # the port end's sits on the frame's own end wall: the USB-C plug fills the gap
BOTTOM = -62.0           # y where the underside meets the plate, just above its bottom edge
STANDOFF = 8.0           # the panel's face clear of the plate: room for the box and cable
RIM = 3.0                # behind the panel, all around
PANEL_TOP = 53.0         # y of the panel's upper edge: 22 mm below the frame's top
HEIGHT = 179.0           # along x: the A1 mini's 180 mm of height, standing on end


def face_frame():
    """The panel's seat along the slope: distances down the face from its top corner C."""
    gap = PANEL_T + 0.4
    groove = LIP + TRAVEL + 0.5
    v_r = 1.6 + groove                                    # the lip's lower end
    v_top = v_r - LIP                                     # the panel's top edge, resting
    v_bot = v_top + PANEL[1] + 2 * FIT                    # its bottom edge, on the ledge
    return gap, v_r, v_top, v_bot, v_bot + LEDGE


def profile(back):
    """The shell's outline in (y, z), the inside's simple outline, and the corners C, B."""
    a = math.radians(TILT)
    down = np.array([-math.sin(a), math.cos(a)])        # down the face, in (y, z)
    out = np.array([math.cos(a), math.sin(a)])           # out of it
    gap, v_r, v_top, v_bot, face = face_frame()
    C = np.array([PANEL_TOP + v_top * math.sin(a), back + STANDOFF])

    def q(v, w):
        return C + v * down + w * out

    top = q(0, gap + LIP_T)
    pts = [(BOTTOM, back), q(face, 0), q(face, PANEL_T), q(v_bot, PANEL_T), q(v_bot, 0), q(v_r, 0),
           q(1.6, 0), q(1.6, gap), q(v_r, gap), q(v_r, gap + LIP_T), top, (top[0], back)]
    inside = [(BOTTOM, back), q(face, 0), C, (C[0], back)]
    return ccw(pts), ccw(inside), C, q(face, 0), (down, out)


def ccw(pts):
    pts = [(float(p[0]), float(p[1])) for p in pts]
    area = sum(s[0] * t[1] - t[0] * s[1] for s, t in zip(pts, pts[1:] + pts[:1]))
    return pts if area > 0 else pts[::-1]


def prism(cs, xa, xb):
    """Extrude a (y, z) cross-section along x from xa to xb."""
    m = Manifold.extrude(cs, xb - xa)                      # (x', y') = (y, z), along z' = x
    return m.transform([[0, 0, 1, xa], [1, 0, 0, 0], [0, 1, 0, 0]])


def place(m, origin, down, out):
    """Map a part built in face coordinates (x, down the face, out of it) into place."""
    return m.transform([[1, 0, 0, 0], [0, down[0], out[0], origin[0]], [0, down[1], out[1], origin[1]]])


def shell(p, f, L):
    back = f["depth"]
    outline, inside, C, B, (down, out) = profile(back)
    x0 = -f["rebate_l"] / 2 - 1.5                       # its port end sits on the frame's end wall
    x1 = x0 + HEIGHT
    xc = (x0 + x1) / 2
    g = prism(CrossSection([outline]), x0, x1)
    hollow = CrossSection([inside]).offset(-WALL, JoinType.Miter, 20.0)
    b = hollow.bounds()
    hollow = hollow + CrossSection.square((b[2] - b[0], WALL + 2)).translate((b[0], back - 1))  # open to the plate
    g = g - prism(hollow, x0 + END_PORT, x1 - END)

    gap, v_r, v_top, v_bot, face = face_frame()
    pl = PANEL[0] + 2 * FIT
    # stops at the panel's ends
    for sx in (-1, 1):
        stop = box(1.6, v_bot - v_top, PANEL_T, cx=xc + sx * (pl / 2 + 0.8), cy=(v_top + v_bot) / 2, z0=-0.02)
        g = g + place(stop, C, down, out)
    # the niche's opening, inside the rim: peaked at its upper end (in print), so it bridges nothing
    u0, u1, w0, w1 = xc - pl / 2 + RIM, xc + pl / 2 - RIM, v_top + RIM, v_bot - RIM
    h = (w1 - w0) / 2
    win = CrossSection([[(u0, w0), (u1 - h, w0), (u1, w0 + h), (u1 - h, w1), (u0, w1)]])
    g = g - place(Manifold.extrude(win, WALL + 1).translate((0, 0, -WALL - 0.5)), C, down, out)
    return g, (C, B, x0, x1)


def backplate(p, f, L, x0, x1):
    """The plate: over the insert and the gap left at the port end, open in the middle (a
    peaked window, so it bridges nothing standing on end), the plug's slot, the fingers."""
    back, t = f["depth"], p["plate_t"]
    xa = -f["rebate_l"] / 2 + p["rebate_fit"]
    g = box(x1 - xa, L["insert_w"], t + 0.3, cx=(xa + x1) / 2, z0=back - t)   # 0.3 into the shell, to fuse
    wx0, wx1 = L["body_cx"] - (L["pl"] - 30) / 2, L["body_cx"] + (L["pl"] - 30) / 2
    wh = (L["pw"] - 30) / 2
    win = CrossSection([[(wx0, -wh), (wx1 - wh, -wh), (wx1, 0), (wx1 - wh, wh), (wx0, wh)]])
    g = g - Manifold.extrude(win, t + 1).translate((0, 0, back - t - 0.5))
    port_y = L["pw"] / 2 - p["port_from_edge"]
    edge = L["body_cx"] - L["pl"] / 2
    g = g - box(40, p["plug_notch_w"], t + 1, cx=edge - 20 + 0.5, cy=port_y, z0=back - t - 0.5)
    return g + fingers(p, L, back)


def backing(p, f, L):
    g, (C, B, x0, x1) = shell(p, f, L)
    return g + backplate(p, f, L, x0, x1), (C, B, x0, x1)


def standing(m, x0):
    """Into print orientation: on its port end."""
    m = m.rotate((0, -90, 0))
    return m.translate((0, 0, -m.bounding_box()[2]))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    kindle = args[0] if args else "pw2"
    f = FRAMES["rodalm13x18"]
    p = dict(P, **KINDLES[kindle])
    L = layout(p, f)
    g, (C, B, x0, x1) = backing(p, f, L)
    name = "solar-rodalm13x18-" + kindle
    mesh = export(standing(g, x0), os.path.join(HERE, name))
    b = mesh.bounds[1] - mesh.bounds[0]
    print("%s: %.0f x %.0f x %.0f mm standing, %.1f cm3, watertight %s" % (
        name, b[0], b[1], b[2], mesh.volume / 1000, mesh.is_watertight))
    print("panel %.0f-%.0f mm above the plate's bottom edge, %.0f mm proud of the frame; x %.1f..%.1f" % (
        B[0] + L["insert_w"] / 2, C[0] + L["insert_w"] / 2, B[1] - f["depth"], x0, x1))
