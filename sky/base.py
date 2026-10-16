"""Settings, the canvas and lettering for sky.py: config.json, the visible area, fonts and
text that fits, and where things are from home.

Everything is drawn on the PW4's landscape 1448x1072 canvas and scaled to a smaller panel
at output (loop.turn), so every number here means the same on a PW2.
"""

import json
import math
import os
import sys
import time

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

# Defaults; config.json overrides all of these. Home is Toronto City Hall.
HOME_LAT = 43.6535
HOME_LON = -79.3839
# Kindles have no compass or accelerometer, so placement is configured by hand.
# HEADING: compass direction you face when reading the screen; the dome turns so that
#          direction is at the bottom, forward up, like a map.
# ROTATE:  degrees to turn the landscape canvas clockwise onto the panel; 90 = Kindle on
#          its side with the "kindle" logo on the right, 270 = logo on the left.
HEADING = 0
ROTATE = 270
PANEL_SIDE = "left"       # the text panel's side; the dome takes the rest
PANEL_W_CFG = None        # config.json "panel_w", for a wider text panel
POWER = {}
NIGHT = ("23:00", "07:00")
FRONTLIGHT = 3            # level (0-24) while on a charger; suspend kills it, so dark on battery
LAST_CFG = None

W, H = 1448, 1072
# config.json "safe" is the part of the screen the frame's mat leaves visible, measured right
# at the mat; "inset" keeps lettering this far inside it. 12 canvas px is 1 mm on either model
SAFE = (0, 0, W, H)
INSET = 12
TEXT = SAFE
CANVAS = None             # the image being drawn, for CachedDraw's pastes


def load_config(args):
    """config.json beside this file overrides the defaults above; flags override config.json.
    Re-read every loop, so editing the file changes the display without a restart."""
    global HEADING, ROTATE, HOME_LAT, HOME_LON, PANEL_SIDE, PANEL_W_CFG, POWER, NIGHT, FRONTLIGHT
    global SAFE, INSET, TEXT, LAST_CFG
    try:
        with open(getattr(args, "config", None) or os.path.join(HERE, "config.json")) as f:
            cfg = json.load(f)
        LAST_CFG = cfg
    except (OSError, ValueError) as e:
        # A typo, or Drive Mode taking /mnt/us away, must not reset the layout or switch off
        # power saving: keep the last good config. Only a first read falls back to defaults
        if LAST_CFG is None:
            cfg = {}
        else:
            cfg = LAST_CFG
            print("config.json unreadable, keeping the last good one: %r" % e, file=sys.stderr, flush=True)
    HEADING = cfg.get("heading", HEADING)
    ROTATE = cfg.get("rotate", ROTATE)
    HOME_LAT = cfg.get("lat", HOME_LAT)
    HOME_LON = cfg.get("lon", HOME_LON)
    # "style": "bold" is the planes frame's old name for a panel on the right
    PANEL_SIDE = cfg.get("panel_side") or ("right" if cfg.get("style") == "bold" else "left")
    PANEL_W_CFG = cfg.get("panel_w")
    POWER = cfg.get("power", {})
    NIGHT = tuple(cfg.get("night", NIGHT))  # ["23:00", "07:00"]
    if cfg.get("tz"):
        # POSIX form ("PST8PDT,M3.2.0,M11.1.0"): the Kindle has no zoneinfo to look names up in
        os.environ["TZ"] = cfg["tz"]
        time.tzset()
    FRONTLIGHT = int(cfg.get("frontlight", FRONTLIGHT))
    INSET = int(cfg.get("inset", 12))
    if getattr(args, "heading", None) is not None:
        HEADING = args.heading
    if getattr(args, "rotate", None) is not None:
        ROTATE = args.rotate
    SAFE = tuple(cfg.get("safe") or SAFE)
    x0, y0, x1, y1 = SAFE
    TEXT = (x0 + INSET, y0 + INSET, x1 - INSET, y1 - INSET)
    return dict(power=POWER, rotate=ROTATE, style=PANEL_SIDE, frontlight=FRONTLIGHT)


def write_json(path, data, **kw):
    """Atomic write; False instead of a crash when the user store is gone. Plugging the
    Kindle into a computer hands /mnt/us to it (Drive Mode), and a write then fails with a
    stale file handle. A skipped save is caught up on by the next one."""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, **kw)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


# ---------- time ----------

def _minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def in_night(when):
    lt = time.localtime(when)
    m = lt.tm_hour * 60 + lt.tm_min
    start, end = _minutes(NIGHT[0]), _minutes(NIGHT[1])
    return m >= start or m < end if start > end else start <= m < end


def next_morning(when):
    """Epoch of the next NIGHT end (e.g. 07:00) after `when`."""
    lt = time.localtime(when)
    end = _minutes(NIGHT[1])
    base = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, end // 60, end % 60, 0, 0, 0, -1))
    return base if base > when else base + 86400


# ---------- geometry ----------

def distance_bearing(lat1, lon1, lat2, lon2):
    """Kilometers and initial bearing (deg true) from point 1 to point 2."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    dist = 2 * 6371.0 * math.asin(math.sqrt(a))
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return dist, (math.degrees(math.atan2(y, x)) + 360) % 360


def compass(brg):
    return ("N", "NE", "E", "SE", "S", "SW", "W", "NW")[int((brg + 22.5) // 45) % 8]


# ---------- lettering ----------

_fonts = {}


def font(name, size):
    # Loading a TTF costs ~10 ms on the Kindle and fit_font() asks for many sizes a frame
    if (name, size) not in _fonts:
        _fonts[name, size] = ImageFont.truetype(os.path.join(HERE, "fonts", name), size)
    return _fonts[name, size]


_bbox, _glyphs = {}, {}


class CachedDraw(ImageDraw.ImageDraw):
    """ImageDraw that renders each (string, font) once and pastes it after that.
    FreeType rasterizing was half the Kindle's frame time, and minute to minute
    most strings don't change."""

    def textbbox(self, xy, text, font=None, *args, **kw):
        if args or kw or font is None:
            return super().textbbox(xy, text, font, *args, **kw)
        key = (text, id(font))
        if key not in _bbox:
            if len(_bbox) > 4000:
                _bbox.clear()  # a clock's every minute is a new string: never let it grow for weeks
            _bbox[key] = super().textbbox((0, 0), text, font)
        b = _bbox[key]
        return (b[0] + xy[0], b[1] + xy[1], b[2] + xy[0], b[3] + xy[1])

    def text(self, xy, text, fill=None, font=None, *args, **kw):
        if args or kw or font is None or not isinstance(fill, int):
            return super().text(xy, text, fill, font, *args, **kw)
        key = (text, id(font))
        if key not in _glyphs:
            if len(_glyphs) > 600:
                _glyphs.clear()
            b = self.textbbox((0, 0), text, font)
            m = Image.new("L", (max(1, b[2] - b[0]), max(1, b[3] - b[1])), 0)
            ImageDraw.Draw(m).text((-b[0], -b[1]), text, fill=255, font=font)
            _glyphs[key] = (m, b[0], b[1])
        m, ox, oy = _glyphs[key]
        CANVAS.paste(fill, (int(round(xy[0] + ox)), int(round(xy[1] + oy))), m)


def text_w(d, s, f):
    b = d.textbbox((0, 0), s, font=f)
    return b[2] - b[0]


def fit(d, s, f, width):
    if text_w(d, s, f) <= width:
        return s
    while s and text_w(d, s + "…", f) > width:
        s = s[:-1]
    return s.rstrip(" ·") + "…"


def fit_font(d, s, name, size, width, floor=34):
    """Largest size (stepping down) at which s fits the width."""
    while size > floor:
        f = font(name, size)
        if text_w(d, s, f) <= width:
            return f
        size -= 4
    return font(name, floor)


def wrap(d, text, face, size, width, floor=56):
    """Word-wrap at a fixed big size; only a single word too wide for the column shrinks."""
    f = font(face, size)
    lines, cur = [], ""
    for word in [w for w in text.split(" ") if w]:  # " " only: NBSP must not break
        trial = (cur + " " + word).strip(" ")
        if cur and text_w(d, trial, f) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return [(ln, f if text_w(d, ln, f) <= width else fit_font(d, ln, face, size, width, floor)) for ln in lines]
