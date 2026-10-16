"""Icons for the sky frame, from open icon fonts rather than drawn by hand: Phosphor
(fill weight) for most, Tabler's satellite, and Weather Icons' 28 moon phases. The fonts
are cut down to just these glyphs by tools/icon_fonts.py; fonts/icons.json maps names.

Glyphs are rendered at 2x, turned if needed, then scaled down, so rotated icons keep
clean edges. Each icon comes with a halo in the page color so it stands off lines behind it.
"""

import json
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
with open(os.path.join(FONTS, "icons.json")) as f:
    GLYPHS = json.load(f)
SS = 2
_fonts, _cache = {}, {}


def cached(fn):
    def wrap(*args):
        key = (fn.__name__,) + args
        if key not in _cache:
            if len(_cache) > 400:
                _cache.clear()
            _cache[key] = fn(*args)
        return _cache[key]
    wrap.__name__ = fn.__name__
    return wrap


def _mask(name, px):
    """The glyph's coverage at px (times SS), cropped to its ink."""
    fname, code = GLYPHS[name]
    if (fname, px) not in _fonts:
        _fonts[fname, px] = ImageFont.truetype(os.path.join(FONTS, fname), px * SS)
    size = px * SS * 2
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).text((size / 2, size / 2), chr(code), font=_fonts[fname, px], fill=255, anchor="mm")
    return m.crop(m.getbbox())


def _finish(shade, alpha, angle, halo):
    if angle:
        shade = shade.rotate(-angle, resample=Image.BICUBIC, expand=True)
        alpha = alpha.rotate(-angle, resample=Image.BICUBIC, expand=True)
    size = (max(1, shade.width // SS), max(1, shade.height // SS))
    shade, alpha = shade.resize(size, Image.LANCZOS), alpha.resize(size, Image.LANCZOS)
    return shade, alpha, alpha.filter(ImageFilter.MaxFilter(2 * halo + 1)) if halo else None


@cached
def glyph(name, px, ink, angle=0, halo=3):
    """A one-color icon: (shade, alpha, halo mask)."""
    m = _mask(name, px)
    return _finish(Image.new("L", m.size, ink), m, angle, halo)


def paste(img, icon, x, y, bg, anchor=(0.5, 0.5)):
    shade, alpha, rim = icon
    ox, oy = int(round(x - shade.width * anchor[0])), int(round(y - shade.height * anchor[1]))
    if rim is not None:
        img.paste(bg, (ox, oy), rim)
    img.paste(shade, (ox, oy), alpha)


@cached
def moon(px, phase, angle, night, lit_shade=255):
    """Weather Icons' moon for phase 0-27 (0 new, 14 full), turned so its lit side faces
    `angle` (screen degrees, clockwise from +x). The glyph draws the rim and the shadow;
    the lit part is a disc under it, white at night and paper by day."""
    m = _mask("moon%d" % phase, px)
    # Waxing glyphs are lit on the right, waning ones on the left
    turn = angle if phase <= 14 else angle + 180
    lit = Image.new("L", m.size, 0)
    inset = max(1, m.width // 30)
    ImageDraw.Draw(lit).ellipse((inset, inset, m.width - 1 - inset, m.height - 1 - inset), fill=255)
    shade = Image.new("L", m.size, lit_shade)
    # At night the shadow side keeps a trace of earthshine rather than vanishing
    shade.paste(40 if night else 0, (0, 0), m)
    alpha = Image.new("L", m.size, 0)
    alpha.paste(255, (0, 0), lit)
    alpha.paste(255, (0, 0), m)
    return _finish(shade, alpha, turn, 3)
