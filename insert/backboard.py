"""Back board for the 13x18 (5x7") frame, replacing the stock hardboard one, with an opening
over the Kindle's charging port and power button.

It holds the way the stock board does: a thinner lip along one short edge slides into the
groove in the frame's rebate wall, the other short edge drops in, and a turn tab on that
edge swings out into the groove on the far side. The lip is flush with the outer face.

The board goes in with the lip on the Kindle's port side. The opening there is open to the
edge and spans the insert's 40 mm cable slot: the power button at one end, the U-turn
adapter at the other, and room behind the adapter to push a plug in and bend the cable out
the back. The tab sits over the insert's finger notch on the far side, where the screw has
room behind the board.

Values marked MEASURE are read off photos: check against the stock board before printing.
Print the board outer face down, the tab flat, both in PETG. Hardware: one M3x8 countersunk
screw (from the inside) and an M3 nyloc nut, snug enough that the tab turns but stays put.
The stock steel tab fits the same screw if the printed one is too thick for the groove.
Run:  uv run --python 3.12 --with manifold3d --with numpy --with trimesh --with pillow \\
          --with networkx --with lxml python backboard.py
"""

import os

from manifold3d import CrossSection, JoinType, Manifold

from insert import HERE, box, export

B = dict(
    # The stock board is 178 x 126 without its lip. 1 mm shorter here, and a 2.5 mm lip, keep
    # the whole board inside the A1 mini's 180 mm bed; the tab takes up the extra 1 mm.
    board_l=177.0,
    board_w=126.0,
    t=2.7,
    lip_t=1.2,
    lip_w=2.5,           # MEASURE: how far the lip stands out from the full-thickness edge
    lip_end=3.0,         # the lip stops short of each corner, as the stock one does
    cut_l=50.0,          # opening: in from the port edge, past the adapter, with room for a plug
    cut_w=40.0,          # the insert's cable slot, power button to port
    cut_r=5.0,
    pivot_in=5.0,        # pivot, in from the far edge
    tab_reach=7.5,       # how far the turned-out tab stands past the board edge (stock: ~7)
    tab_w=8.0,
    tab_t=1.0,           # MEASURE: the stock steel tab is thinner; the groove must take this
    screw_d=3.4,
    csink_d=6.6,         # M3 countersunk head, flush with the inner face
)


def rounded(lx, ly, r):
    return CrossSection.square((lx - 2 * r, ly - 2 * r), center=True).offset(r, JoinType.Round)


def board(b):
    """Outer face on z=0. +x toward the port edge."""
    L, W, t = b["board_l"], b["board_w"], b["t"]
    solid = box(L, W, t)
    solid = solid + box(b["lip_w"], W - 2 * b["lip_end"], b["lip_t"], cx=L / 2 + b["lip_w"] / 2)

    # Opening, through the lip and open to the port edge; only its inner corners are rounded
    x_in = L / 2 - b["cut_l"]
    sec = rounded(b["cut_l"] + 2 * b["cut_r"] + b["lip_w"], b["cut_w"], b["cut_r"])
    hole = Manifold.extrude(sec, t + 1).translate((x_in + (b["cut_l"] + 2 * b["cut_r"] + b["lip_w"]) / 2, 0, -0.5))
    solid = solid - hole

    # Pivot: plain hole, countersunk from the inner face
    px = -L / 2 + b["pivot_in"]
    solid = solid - Manifold.cylinder(t + 1, b["screw_d"] / 2, circular_segments=48).translate((px, 0, -0.5))
    depth = (b["csink_d"] - b["screw_d"]) / 2           # 90 degree head
    cone = Manifold.cylinder(depth + 0.01, b["screw_d"] / 2, b["csink_d"] / 2, circular_segments=48)
    solid = solid - cone.translate((px, 0, t - depth))
    return solid


def tab(b):
    """Lies flat; the pivot end round, the reach end round."""
    r = b["tab_w"] / 2
    span = b["pivot_in"] + b["tab_reach"] - r
    sec = CrossSection.circle(r, 48) + CrossSection.circle(r, 48).translate((span, 0))
    sec = sec.hull() - CrossSection.circle(b["screw_d"] / 2, 48)
    return Manifold.extrude(sec, b["tab_t"])


def preview(b, path, scale=4):
    """Seen from behind the frame, port edge on the left as in the photos, tab turned out."""
    from PIL import Image, ImageDraw
    L, W = b["board_l"], b["board_w"]
    pad = 20
    Wpx, Hpx = int((L + 2 * pad) * scale), int((W + 2 * pad) * scale)
    im = Image.new("RGB", (Wpx, Hpx), (255, 255, 255))
    d = ImageDraw.Draw(im)

    def xy(x, y):        # x measured from the port edge, rightward
        return pad * scale + (x + b["lip_w"]) * scale, Hpx / 2 - y * scale

    def rect(x0, y0, x1, y1, **kw):
        (a, c), (e, f) = xy(x0, y1), xy(x1, y0)
        d.rectangle((a, c, e, f), **kw)

    rect(-b["lip_w"], -W / 2 + b["lip_end"], 0, W / 2 - b["lip_end"], fill=(150, 150, 150))
    rect(0, -W / 2, L, W / 2, fill=(60, 60, 60))
    a, c = xy(-b["lip_w"] - 1, b["cut_w"] / 2)
    e, f = xy(b["cut_l"], -b["cut_w"] / 2)
    d.rounded_rectangle((a, c, e, f), radius=b["cut_r"] * scale, fill=(255, 255, 255))
    # The insert behind: Kindle edge 5.75 mm in, the adapter reaching ~15 mm
    rect(5.75, -W / 2 + 7, L, W / 2 - 7, outline=(200, 160, 90), width=2)
    rect(2, -13, 15, -2, fill=(240, 120, 60))
    px = L - b["pivot_in"]
    rect(px - b["tab_w"] / 2 + 4, -b["tab_w"] / 2, L + b["tab_reach"], b["tab_w"] / 2, fill=(110, 160, 220))
    d.text((8, 8), "back view: lip (grey) left, opening over port, tab (blue) turned out right", fill=(0, 0, 0))
    im.save(path)


if __name__ == "__main__":
    plate = board(B)
    # Tab beside the board on the bed: 180 x 180 fits an A1 mini
    piece = tab(B).translate((-B["board_l"] / 2 + 10, -B["board_w"] / 2 - 15, 0))
    mesh = export(plate + piece, os.path.join(HERE, "backboard-rodalm13x18"))
    preview(B, os.path.join(HERE, "preview-backboard.png"))
    print("board %.0f x %.0f x %.1f mm (%.0f with lip), %.0f cm3, watertight %s" % (
        B["board_l"], B["board_w"], B["t"], B["board_l"] + B["lip_w"], mesh.volume / 1000, mesh.is_watertight))
