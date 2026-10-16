"""Frame insert for the Kindle Paperwhite 10th gen (PW4) in an IKEA RÖDALM frame.

One printed piece, printed face-down (the front is the visible mat):
  - a mat window centered in the frame, with a 45° mat bevel;
  - behind it a friction-fit pocket for the Kindle (landscape, port/logo edge on the left);
  - room beside the charging port for the plug, the cable leaving out the back;
  - a finger notch to lift the Kindle out.

The Kindle's screen sits off-center in its body (the logo bezel is deeper), and the plug
needs room on that side too, so the screen ends up off-center in the frame. The window is
therefore the largest rectangle that is centered in the frame AND inside the screen; the
strip of screen it hides is reported as the `safe` area for sky/config.json, so the
display lays itself out in exactly the visible part.

Values marked MEASURE are estimates: confirm with a ruler/calipers before printing.
Print face-down in PETG (PLA springs creep), no brim or skirt. Fits an A1 mini bed.
Run:  uv run --python 3.12 --with manifold3d --with numpy --with trimesh --with pillow \\
          --with networkx --with lxml python insert.py [rodalm13x18|rodalm21x30] [pw4|pw2] [--test[=strip]] [--plate] [--rebate=LxW] [--plug-room=MM]
--test writes a quick fit-check piece instead of the insert (see coupon() and strip()).
"""

import os
import sys

import numpy as np
from manifold3d import CrossSection, Manifold

HERE = os.path.dirname(os.path.abspath(__file__))

FRAMES = {
    # IKEA RÖDALM 13x18 cm, landscape, with its polystyrene inner frame taken out: 183 x 131.2
    # and 24 deep to the back edge, measured (the 128 of the first test strip was inside that
    # inner frame). Its front opening is the whole rebate, so the printed face IS the mat. The room beside the port is
    # for a right-angle plug, about 10 mm past the Kindle's edge (from a photo; a flat FPC
    # extension needs 5.5 and leaves a 10 mm wider window).
    # `depth` fills the rebate: the insert's walls stop plate_t short of the back edge and the
    # back plate (--plate) closes it flush, in place of the stock back board.
    "rodalm13x18": dict(rebate_l=183.0, rebate_w=131.2, depth=24.0, ikea_mat=False, plug_room=10.5,
                        ikea_opening_l=0, ikea_opening_w=0),
    # IKEA RÖDALM 21x30 cm, landscape: printed inner mat behind IKEA's paper mat (double mat),
    # a rim drops into the IKEA opening to center it; any right-angle plug fits beside it.
    "rodalm21x30": dict(rebate_l=300.0, rebate_w=210.0, ikea_mat=True, plug_room=0.0,
                        ikea_opening_l=170.0, ikea_opening_w=120.0),   # MEASURE the opening
}

P = dict(
    kindle_l=166.0,          # measured 2026-10-03 (ruler)
    kindle_w=115.7,          # calipers
    kindle_t=8.5,
    screen_l=122.4,          # active area: 1448 px at 300 ppi
    screen_w=90.7,           # 1072 px
    bezel_port=23.5,         # port/logo edge of the body to the screen
    bezel_top=20.5,          # opposite edge to the screen
    # Along the port edge the USB port starts 40 mm from one side and the power button ends
    # 40 mm from the other; one slot centered on the edge leaves both open
    port_from_edge=57.85,
    fit=0.0,                 # pocket clearance per side: 0.25 let the Kindle rattle
    rebate_fit=0.5,          # insert clearance to the frame per side
    window_overlap=1.5,      # mat covers this much of the screen edge; absorbs bezel estimate error
    ikea_mat_t=1.4,          # MEASURE (21x30 only)
    face_t=1.6,              # mat thickness in front of the Kindle
    rim_h=0.8,
    bevel=1.2,
    plug_notch_w=40.0,
    finger_notch=22.0,
    # Holding it all without a back board (print in PETG: PLA springs creep)
    spring_len=30.0,         # side spring tabs: rise from the mat plate, free at the back
    spring_t=1.8,            # tab thickness
    spring_gap=1.0,          # slot behind the tab
    spring_bump=1.4,         # outward bump -> 0.9 mm interference with rebate_fit 0.5
    lip_len=24.0,            # snap lips on the long sides of the pocket
    lip_over=1.0,            # how far a lip hangs over the Kindle's back edge
    lip_t=1.2,
    back_fit=0.3,            # pocket depth over the Kindle's thickness
    # The Kindle's back edge is rounded, so a lip level with its back catches nothing: the
    # lip's tip sits this far below the back and its 45° underside presses on the curve
    lip_drop=1.0,
    far_wall=2.5,            # thinnest the insert's far end wall gets before it slides over
    bed_l=179.0,             # longest insert the A1 mini prints
    plate_t=2.4,             # back plate, flush with the frame's back edge
    # The plate holds itself in the frame the way the insert does: leaf-spring fingers reach
    # forward into pockets in the insert's long walls, between the insert's own springs, and
    # their bumps press on the frame. They taper at 45° so they print standing too.
    finger_len=12.0,
    finger_t=1.8,
    finger_root=20.0,        # wide at the plate, finger_root - finger_len at the tip
    finger_flex=1.0,         # room in the pocket to flex inward
    px_per_mm=1448 / 122.4,
)


# The PW2 (2013): 169 x 117 by printed gauges, the rest measured from photos on 2026-10-08
# in two independent passes. Its port and the thick logo bezel share an edge, and its
# right-angle adapter takes 10.5 mm by the outline test, plus 0.5 to spare. Along the port edge the plug sits 45.4 mm from the
# top as mounted and the power button ends about 75 mm down; one slot leaves both open. Its
# panel is 758 x 1024 at 212 ppi, drawn from the same 1448-px canvas, so a pixel is wider.
KINDLES = {
    "pw4": {},
    "pw2": dict(kindle_l=169.0, kindle_w=117.0, kindle_t=9.1, bezel_port=27.0, bezel_top=18.6,
                screen_l=122.7, screen_w=90.8, px_per_mm=1448 / 122.7,
                plug_room=11.0, plug_notch_w=38.0, port_from_edge=57.5),
}


def box(lx, ly, lz, cx=0.0, cy=0.0, z0=0.0):
    return Manifold.cube((lx, ly, lz), center=True).translate((cx, cy, z0 + lz / 2))


def layout(p, f):
    """Where things sit, in mm, origin at the frame center, +x away from the port."""
    if f["ikea_mat"]:
        insert_l, insert_w = 178.0, 128.0     # A1 mini bed
    else:
        insert_l = min(f["rebate_l"] - 2 * p["rebate_fit"], p["bed_l"])
        insert_w = f["rebate_w"] - 2 * p["rebate_fit"]
    pl, pw = p["kindle_l"] + 2 * p["fit"], p["kindle_w"] + 2 * p["fit"]
    # Ideal: screen centered. Screen center is (bezel_port - bezel_top)/2 from body center,
    # toward the far side, so the body sits that far toward the port...
    body_cx = -(p["bezel_port"] - p["bezel_top"]) / 2.0
    # ...unless the port side then lacks room for the plug: push the body away from it.
    # (the plug's room runs to the frame's wall, past the insert's own end)
    port_room = f["rebate_l"] / 2 + (body_cx - pl / 2)
    need = p.get("plug_room", f["plug_room"])
    if not f["ikea_mat"] and port_room < need:
        body_cx += need - port_room
    # The insert sits centered, so the gaps at the frame's ends match, unless the body has
    # been pushed so far that the far wall gets thin: then it slides toward the far end,
    # never closer to the frame's wall than its fit
    insert_cx = 0.0
    if not f["ikea_mat"]:
        thin = p["far_wall"] - (insert_l / 2 - (body_cx + pl / 2))
        insert_cx = min(max(thin, 0.0), f["rebate_l"] / 2 - p["rebate_fit"] - insert_l / 2)
    screen_cx = body_cx + (p["bezel_port"] - p["bezel_top"]) / 2.0
    s0, s1 = screen_cx - p["screen_l"] / 2, screen_cx + p["screen_l"] / 2
    # Largest window centered on the frame and inside the screen (minus the overlap)
    half = min(-s0, s1) - p["window_overlap"]
    wl = 2 * half
    ww = p["screen_w"] - 2 * p["window_overlap"]
    # Visible part of the screen in landscape canvas pixels (canvas x=0 at the port side)
    k = p["px_per_mm"]
    safe = [round((-half - s0) * k), round(p["window_overlap"] * k),
            round((half - s0) * k), round((p["screen_w"] - p["window_overlap"]) * k)]
    return dict(insert_l=insert_l, insert_w=insert_w, insert_cx=insert_cx, pl=pl, pw=pw,
                body_cx=body_cx, screen_cx=screen_cx, wl=wl, ww=ww, safe=safe,
                port_wall=(body_cx - pl / 2) - (insert_cx - insert_l / 2),
                far_wall=(insert_cx + insert_l / 2) - (body_cx + pl / 2), side_wall=(insert_w - pw) / 2)


def wedge(x0, x1, y_wall, inward, z_tip, z_back, overhang):
    """A ramped lip along x: its tip at z_tip, a 45° underside below it, and a ramp sloping
    to nothing at z_back."""
    y_in = y_wall + inward * overhang
    pts = [(x, y, z) for x in (x0, x1) for (y, z) in
           ((y_wall, z_tip - overhang), (y_in, z_tip), (y_wall, z_back))]
    return Manifold.hull_points(pts)


def build(p, f, L):
    rim = f["ikea_mat"]
    rim_h = p["rim_h"] if rim else 0.0
    front = rim_h + p["face_t"]
    z_tip = front + p["kindle_t"] - p["lip_drop"]
    body_t = p["face_t"] + p["kindle_t"] + p["back_fit"] + p["lip_t"]
    back = rim_h + body_t
    il, iw, icx = L["insert_l"], L["insert_w"], L["insert_cx"]
    solid = box(il, iw, body_t, cx=icx, z0=rim_h)
    if rim:
        solid = solid + box(f["ikea_opening_l"] - 0.6, f["ikea_opening_w"] - 0.6, rim_h)

    # Window with a mat bevel widening toward the viewer
    bev = min(p["bevel"], front)
    wl, ww = L["wl"], L["ww"]
    sec = CrossSection.square((wl + 2 * bev, ww + 2 * bev), center=True)
    bevel = Manifold.extrude(sec, bev, scale_top=(wl / (wl + 2 * bev), ww / (ww + 2 * bev)))
    solid = solid - bevel.translate((0, 0, -0.001)) - box(wl, ww, front + 0.02, z0=-0.01)

    # Kindle pocket, open to the back (the Kindle presses in from behind)
    cx, pl, pw = L["body_cx"], L["pl"], L["pw"]
    solid = solid - box(pl, pw, body_t + 1, cx=cx, z0=front)

    # Snap lips: ramped overhangs on the long sides, each on a flexible tab so it can
    # spring outward as the Kindle goes in, then snap over its back edge
    for sx in (-1, 1):
        x0 = cx + sx * (pl / 4) - p["lip_len"] / 2
        for sy in (-1, 1):
            y_wall = sy * pw / 2
            solid = solid + wedge(x0, x0 + p["lip_len"], y_wall, -sy, z_tip, back, p["lip_over"])
            slot_y = y_wall + sy * (p["spring_t"] + p["spring_gap"] / 2)
            solid = solid - box(p["lip_len"] + 4, p["spring_gap"], back - front - 1.5,
                                cx=x0 + p["lip_len"] / 2, cy=slot_y, z0=front + 1.5 + 0.01)
            for ex in (x0 - 2, x0 + p["lip_len"] + 2):
                solid = solid - box(p["spring_gap"], p["spring_t"] + p["spring_gap"], back - front - 1.5,
                                    cx=ex, cy=y_wall + sy * (p["spring_t"] + p["spring_gap"]) / 2,
                                    z0=front + 1.5 + 0.01)

    # Side springs: tabs in the long walls, rooted in the mat plate, free at the back, with
    # a bump that presses on the frame's rebate walls. None on the short ends: their bumps
    # would push the length past the 180 mm A1 mini bed.
    h = back - front
    n = p["spring_len"]
    for sgn in (-1, 1):
        out = sgn * iw / 2
        slot_c = out - sgn * (p["spring_t"] + p["spring_gap"] / 2)
        for along in (icx - il / 4, icx + il / 4):
            solid = solid - box(n, p["spring_gap"], h + 0.1, cx=along, cy=slot_c, z0=front)
            for e in (along - n / 2, along + n / 2):
                solid = solid - box(p["spring_gap"], p["spring_t"] + p["spring_gap"] + 0.2, h + 0.1,
                                    cx=e, cy=out - sgn * (p["spring_t"] + p["spring_gap"]) / 2, z0=front)
            solid = solid + box(n - 4, p["spring_bump"], 3, cx=along, cy=out + sgn * p["spring_bump"] / 2, z0=back - 3)

    port_y = pw / 2 - p["port_from_edge"]
    # Plug notch beside the port, open to the side and back
    edge = cx - pl / 2
    solid = solid - box(40, p["plug_notch_w"], body_t + 1, cx=edge - 20 + 0.5, cy=port_y, z0=front)

    # Finger notch on the far edge: push the Kindle out from the side
    far = cx + pl / 2
    solid = solid - box(14, p["finger_notch"], body_t + 1, cx=far + 5, z0=front + 1.2)

    # Deepen the walls to the frame's depth, except over the springs and lips: taller tabs
    # would be softer
    depth = f.get("depth", 0.0) - p["plate_t"]
    if depth <= back:
        return solid, back
    ext = box(il, iw, depth - back + 0.01, cx=icx, z0=back - 0.01) - box(pl, pw, depth, cx=cx)
    for sx in (-1, 1):
        lip0 = cx + sx * pl / 4 - p["lip_len"] / 2
        x0 = min(lip0 - 3, icx + sx * il / 4 - n / 2) - 1
        x1 = max(lip0 + p["lip_len"] + 3, icx + sx * il / 4 + n / 2) + 1
        ext = ext - box(x1 - x0, iw + 1, depth, cx=(x0 + x1) / 2)
    ext = ext - box(40, p["plug_notch_w"], depth, cx=edge - 20 + 0.5, cy=port_y)
    ext = ext - box(14, p["finger_notch"], depth, cx=far + 5)
    solid = solid + ext
    iw = L["insert_w"]
    r, fl = p["finger_root"], p["finger_len"]
    for x, sy in finger_spots(L):
        a, b = sy * (iw / 2 - p["finger_t"] - p["finger_flex"]), sy * (iw / 2 + 1)
        solid = solid - box(r + 0.8, abs(b - a), fl + 1.8, cx=x, cy=(a + b) / 2, z0=depth - fl - 0.8)
    return solid, depth


def finger_spots(L):
    """Along each long wall: the ends and the middle, clear of the insert's springs and lips."""
    return [(L["insert_cx"] + dx, sy) for dx in (-72.0, 0.0, 72.0) for sy in (-1, 1)]


def fingers(p, L, back):
    """The plate's leaf springs, reaching forward from its front face at z = back - plate_t."""
    iw, t = L["insert_w"], p["plate_t"]
    r, fl, ft, bump = p["finger_root"], p["finger_len"], p["finger_t"], p["spring_bump"]
    z0 = back - t
    g = None
    for x, sy in finger_spots(L):
        tip = z0 - fl
        # the lower edge (in x) rises 45° toward the tip, so standing on end it never overhangs
        cs = CrossSection([[(x - r / 2, z0 + 0.3), (x - r / 2 + fl, tip), (x + r / 2, tip), (x + r / 2, z0 + 0.3)]])
        m = Manifold.extrude(cs, ft)                      # (x, z) extruded along +y'
        m = m.transform([[1, 0, 0, 0], [0, 0, 1, (iw / 2 - ft) if sy > 0 else -iw / 2], [0, 1, 0, 0]])
        y0 = sy * iw / 2
        xa, xb = x - r / 2 + fl + 0.5, x + r / 2 - 0.5
        pts = [(xx, yy, zz) for xx in (xa, xb) for (yy, zz) in
               ((y0 - sy * 0.3, tip + 0.3), (y0 + sy * bump, tip + 1.8), (y0 + sy * bump, tip + 3.8),
                (y0 - sy * 0.3, tip + 5.3))]
        m = m + Manifold.hull_points(pts)                 # ramped bump, against the frame
        g = m if g is None else g + m
    return g


def plate(p, f, L):
    """The back, closing the insert flush with the frame's back edge, in place: its front face
    on the insert at z = depth - plate_t, fingers forward."""
    t, back = p["plate_t"], f["depth"]
    g = box(L["insert_l"], L["insert_w"], t, cx=L["insert_cx"], z0=back - t)
    # Only the rim has to be solid: it carries the fingers and sits on the insert's walls
    g = g - box(L["pl"] - 30, L["pw"] - 30, t + 1, cx=L["body_cx"], z0=back - t - 0.5)
    # the plug notch stays open to the back, so the cable can leave
    port_y = L["pw"] / 2 - p["port_from_edge"]
    edge = L["body_cx"] - L["pl"] / 2
    g = g - box(40, p["plug_notch_w"], t + 1, cx=edge - 20 + 0.5, cy=port_y, z0=back - t - 0.5)
    return g + fingers(p, L, back)


def export(solid, stem):
    import trimesh
    m = solid.to_mesh()
    mesh = trimesh.Trimesh(vertices=np.asarray(m.vert_properties)[:, :3], faces=np.asarray(m.tri_verts))
    mesh.export(stem + ".stl")
    mesh.export(stem + ".3mf")
    return mesh


def preview(p, f, L, path, scale=5):
    """Front view as seen through the frame, with the hidden Kindle and screen ghosted in."""
    from PIL import Image, ImageDraw
    fl, fw = f["rebate_l"], f["rebate_w"]
    W, H = int((fl + 40) * scale), int((fw + 40) * scale)
    im = Image.new("RGB", (W, H), (196, 170, 132))      # birch-ish frame
    d = ImageDraw.Draw(im)

    def rect(cx, cy, lx, ly, **kw):
        d.rectangle((W / 2 + (cx - lx / 2) * scale, H / 2 - (cy + ly / 2) * scale,
                     W / 2 + (cx + lx / 2) * scale, H / 2 - (cy - ly / 2) * scale), **kw)

    rect(0, 0, fl, fw, fill=(248, 247, 243))                                  # mat
    rect(L["body_cx"], 0, p["kindle_l"], p["kindle_w"], outline=(215, 212, 205), width=2)   # hidden body
    rect(L["screen_cx"], 0, p["screen_l"], p["screen_w"], outline=(230, 190, 120), width=2)  # full screen
    rect(0, 0, L["wl"], L["ww"], fill=(222, 224, 219), outline=(120, 120, 118), width=2)     # window
    port_y = L["pw"] / 2 - p["port_from_edge"]
    rect(L["body_cx"] - p["kindle_l"] / 2 - 3, port_y, 6, 10, fill=(240, 120, 60))          # plug
    im.save(path)


def coupon(p, f, L, solid):
    """A quick fit check: the insert with a 0.6 mm mat and walls cut 3 mm above it, except
    full height where the snap lips and side springs are. One print tests the insert in the
    frame, the springs against it, the Kindle in the pocket and under the lips, the slot over
    the port and button, and the window over the screen."""
    front = (p["rim_h"] if f["ikea_mat"] else 0.0) + p["face_t"]
    keep = box(1000, 1000, 3.6, z0=front - 0.6)
    cx, pl, pw, il = L["body_cx"], L["pl"], L["pw"], L["insert_l"]
    for sx in (-1, 1):
        lip0 = cx + sx * pl / 4 - p["lip_len"] / 2
        spring = L["insert_cx"] + sx * il / 4
        x0 = min(lip0, spring - p["spring_len"] / 2) - 3
        x1 = max(lip0 + p["lip_len"], spring + p["spring_len"] / 2) + 3
        for sy in (-1, 1):
            y0 = sy * (pw / 2 - p["lip_over"] - 0.5)
            y1 = sy * (L["insert_w"] / 2 + p["spring_bump"] + 1)
            keep = keep + box(x1 - x0, abs(y1 - y0), 1000, cx=(x0 + x1) / 2, cy=(y0 + y1) / 2,
                              z0=front - 0.6)
    return (solid ^ keep).translate((0, 0, 0.6 - front))


def strip(p, f, L, solid):
    """A full-height slice across the width through a pair of snap lips and side springs:
    the cheapest check of the fit across the frame and of both springs and lips."""
    front = (p["rim_h"] if f["ikea_mat"] else 0.0) + p["face_t"]
    cx, pl, il = L["body_cx"], L["pl"], L["insert_l"]
    lip0 = cx - pl / 4 - p["lip_len"] / 2
    spring = L["insert_cx"] - il / 4
    x0 = min(lip0, spring - p["spring_len"] / 2) - 3
    x1 = max(lip0 + p["lip_len"], spring + p["spring_len"] / 2) + 3
    piece = solid ^ box(x1 - x0, 1000, 1000, cx=(x0 + x1) / 2, z0=-1)
    # The window would leave a thin bar between the two sides, which would flex and spoil
    # the spring test
    return piece + box(x1 - x0, L["ww"] + 2, front, cx=(x0 + x1) / 2)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = dict(a[2:].partition("=")[::2] for a in sys.argv[1:] if a.startswith("--"))
    frame = args[0] if args else "rodalm13x18"
    kindle = args[1] if len(args) > 1 else "pw4"
    f = dict(FRAMES[frame])
    P = dict(P, **KINDLES[kindle])
    # The PW4 files keep their original names
    name = frame if kindle == "pw4" else frame + "-" + kindle
    # --rebate=180x128 tries another frame size without editing FRAMES
    if opts.get("rebate"):
        f["rebate_l"], f["rebate_w"] = map(float, opts["rebate"].split("x"))
        name += "-" + opts["rebate"]
    # --plug-room=4.75 trades cable room beside the port for a screen centered in the window
    if opts.get("plug-room"):
        f["plug_room"] = float(opts["plug-room"])
        name += "-plug" + opts["plug-room"]
    # Any parameter can be tried from the command line, e.g. --fit=0.1
    for k in set(opts) & set(P):
        P[k] = float(opts[k])
    L = layout(P, f)
    solid, thick = build(P, f, L)
    if "plate" in opts:
        if "depth" not in f:
            sys.exit("--plate: %s has no measured depth, so its insert has no plate" % frame)
        # printed back face down, fingers up
        pl8 = plate(P, f, L).rotate((180, 0, 0))
        mesh = export(pl8.translate((0, 0, -pl8.bounding_box()[2])), os.path.join(HERE, "plate-" + name))
        print("plate-%s: %.1f cm3, watertight %s" % (name, mesh.volume / 1000, mesh.is_watertight))
        sys.exit()
    if "test" in opts:
        # --test=strip for the strip alone
        if opts["test"] == "strip":
            piece, name = strip(P, f, L, solid), name + "-strip"
        else:
            piece = coupon(P, f, L, solid)
        mesh = export(piece, os.path.join(HERE, "test-" + name))
        b = mesh.bounds[1] - mesh.bounds[0]
        print("test-%s: %.0f x %.0f x %.1f mm, %.1f cm3, watertight %s" % (
            name, b[0], b[1], b[2], mesh.volume / 1000, mesh.is_watertight))
        sys.exit()
    mesh = export(solid, os.path.join(HERE, "insert-" + name))
    preview(P, f, L, os.path.join(HERE, "preview-" + name + ".png"))
    print("%s: %.0f x %.0f x %.1f mm, %.0f cm3, watertight %s" % (
        name, L["insert_l"], L["insert_w"], thick, mesh.volume / 1000, mesh.is_watertight))
    print("window %.1f x %.1f mm (screen %.1f x %.1f); walls: port %.1f, far %.1f, sides %.1f mm" % (
        L["wl"], L["ww"], P["screen_l"], P["screen_w"], L["port_wall"], L["far_wall"], L["side_wall"]))
    if kindle == "pw4":
        print('config.json  "safe": %s' % L["safe"])
    else:
        print("safe: measure it with tools/grid.sh; this Kindle's screen sits differently")
