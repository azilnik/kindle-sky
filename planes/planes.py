#!/usr/bin/env python3
"""Planes overhead, drawn on a jailbroken Kindle Paperwhite 10th gen (1072x1448, 16 grays).
Also runs on a Paperwhite 2 (758x1024): the same canvas, scaled down at output.

Fetches live ADS-B positions, looks up routes and aircraft types, draws a map and a
story panel with Pillow, and pushes the frame to the e-ink screen with FBInk.

Preview on a laptop:  python3 planes.py --sample samples/crowded.json --rotate 0 --out x.png
Settings live in config.json beside this file (see README.md).
"""

import argparse
import json
import math
import os
import re
import sys
import time

import loop
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

# Defaults; config.json overrides all of these. Home is Toronto City Hall.
HOME_LAT = 43.6535
HOME_LON = -79.3839
LOCAL_CITY = "Toronto"
AIRPORTS = (
    ("YYZ", 43.6777, -79.6248),
    ("YTZ", 43.6275, -79.3962),
)
RANGE_KM = 30
RINGS_KM = (5, 15, 30)
KM_PER_NM = 1.852

# Kindles have no compass or accelerometer, so placement is configured by hand.
# HEADING: compass direction you face when reading the screen; the map turns so
#          that direction points up (0 = north-up).
# ROTATE:  degrees to turn the landscape canvas clockwise onto the panel; 90 = Kindle
#          on its side with the "kindle" logo on the right, 270 = logo on the left.
HEADING = 0
ROTATE = 270
STYLE = "bold-right"
POWER = {}
# One flight big ("bold"), or the neighbours packed in ("detailed")
BOLD = dict(labeled=1, feat_size=56, size=28, rings=False, lake=204, sub=False, label="blabel", panel_w=470)
STYLES = {
    "bold-right": dict(BOLD, map_side="right"),   # story on the left, map on the right
    "bold": dict(BOLD),                           # map on the left, story on the right
    "bold-traffic": dict(BOLD, chart=True),       # bold plus a chart of the day's traffic
    "detailed": dict(labeled=8, feat_size=34, size=24, rings=True, lake=221, sub=True, label="label"),
}

# Landscape canvas; rotated into the panel's native 1072x1448 portrait at output
W, H = 1448, 1072
PANEL_W = 420
# config.json "panel_w": an unframed PW2 shows more of the canvas, and a wider story panel
# there keeps long city names on one line at full size
PANEL_W_CFG = None
# config.json "inset": text keeps this far inside `safe`, which is the visible area measured
# right at the mat. 12 canvas px is 1 mm on either model (1448 px across 122.4 mm of screen).
# The map, lake and planes still run out to `safe` itself
INSET = 12


def apply_layout(safe):
    """Fit everything inside the part of the screen a frame's mat leaves visible.
    safe = (x0, y0, x1, y1) in landscape canvas pixels; measure it with a grid.
    TEXT is the same box INSET further in, for everything that's lettering."""
    global SAFE, TEXT, PANEL_X, PANEL_R, MAP_BOX, LABEL_BOX, RADAR, RADAR_X, RADAR_Y
    SAFE = tuple(safe)
    x0, y0, x1, y1 = SAFE
    i = INSET
    TEXT = (x0 + i, y0 + i, x1 - i, y1 - i)
    pw = PANEL_W_CFG or STYLES[STYLE].get("panel_w", PANEL_W)
    # The map fills everything beside the panel, past its outer ring. The inset moves the
    # panel's text in from the mat but not its width, so wrapping and the map are unchanged:
    # it eats into the gap between them instead
    if STYLES[STYLE].get("map_side") == "right":
        PANEL_X, PANEL_R = x0 + 8 + i, x0 + pw + i
        MAP_BOX = (x0 + pw + 24, y0, x1, y1)
        LABEL_BOX = (MAP_BOX[0], TEXT[1], TEXT[2], TEXT[3])
    else:
        PANEL_X, PANEL_R = x1 - pw - i, x1 - 8 - i
        MAP_BOX = (x0, y0, x1 - pw - 24, y1)
        LABEL_BOX = (TEXT[0], TEXT[1], MAP_BOX[2], TEXT[3])
    RADAR = min(MAP_BOX[2] - MAP_BOX[0], y1 - y0) - 12
    RADAR_X = (MAP_BOX[0] + MAP_BOX[2] - RADAR) // 2
    RADAR_Y = (y0 + y1 - RADAR) // 2


apply_layout((0, 0, W, H))

INK = 0
DIM = 68
FAINT = 136
FAINT_BAR = 204
PAPER = 255

# Same readsb JSON from both; the second takes over when the first rate-limits (429)
ADSB_URLS = (
    # Plain HTTP on purpose: public position data, and a TLS handshake costs the
    # Kindle's CPU about a second of awake time on every fetch
    "http://api.adsb.lol/v2/point/{lat}/{lon}/{nm}",
    "https://opendata.adsb.fi/api/v2/lat/{lat}/lon/{lon}/dist/{nm}",
)
ROUTE_URL = "https://api.adsbdb.com/v0/callsign/{cs}"
AIRFRAME_URL = "https://api.adsbdb.com/v0/aircraft/{hex}"

# adsbdb's airline mapping is wrong for some carriers (it puts PTR on a Nova Scotia
# government fleet), so trust the callsign prefix for the ones common over Toronto.
AIRLINES = {
    "ACA": "Air Canada", "JZA": "Air Canada Express", "ROU": "Air Canada Rouge",
    "PTR": "Porter", "WJA": "WestJet", "WEN": "WestJet Encore", "SWG": "Sunwing",
    "TSC": "Air Transat", "FLE": "Flair", "UAL": "United", "DAL": "Delta",
    "AAL": "American", "RPA": "Republic", "SKW": "SkyWest", "ENY": "Envoy",
    "EDV": "Endeavor", "JIA": "PSA", "ASH": "Mesa", "JBU": "JetBlue",
    "BAW": "British Airways", "AFR": "Air France", "KLM": "KLM", "DLH": "Lufthansa",
    "SWR": "Swiss", "AIC": "Air India", "UAE": "Emirates", "ETD": "Etihad",
    "CPA": "Cathay Pacific", "EJA": "NetJets", "LXJ": "Flexjet", "FDX": "FedEx",
    "UPS": "UPS", "CJT": "Cargojet", "POE": "Porter", "TAP": "TAP Air Portugal",
    "ELY": "El Al", "THY": "Turkish", "ITY": "ITA Airways", "QTR": "Qatar",
    "CAL": "China Airlines", "CCA": "Air China", "EIN": "Aer Lingus", "IBE": "Iberia",
    "VIR": "Virgin Atlantic", "ICE": "Icelandair", "CMP": "Copa", "AMX": "Aeromexico",
    "LOT": "LOT", "FFT": "Frontier", "NKS": "Spirit", "PDT": "Piedmont",
}

# Timing. The screen redraws every minute (loop.py) from dead-reckoned positions; the network
# is only touched every FETCH_S (joining Wi-Fi is the Kindle's biggest power cost).
FETCH_S = 600             # routine: cruising traffic dead-reckons well for 10 minutes
FETCH_BUSY_S = 300        # featured plane low (turning to land / climbing out) or about to leave
QUIET_FETCH_S = 900       # nothing in view: check back less often
MAX_PROJECT_S = 660       # never guess further than this past a real fix
FETCH_MARGIN_NM = 8       # fetch a ring beyond the map so arrivals are ready to slide in
# Night: one constellation of the day's traffic, Wi-Fi off, no redraws until morning.
# Near empty (loop.battery_low) it parks on the constellation too, since e-ink keeps the
# last image once the battery dies
NIGHT = ("23:00", "07:00")
FRONTLIGHT = 3            # level (0-24) while on a charger; suspend kills it, so dark on battery

CACHE_PATH = os.path.join(HERE, "cache.json")
ROUTE_TTL = 6 * 3600


_fonts = {}


def font(name, size):
    # Loading a TTF costs ~10 ms on the Kindle and fit_font() asks for many sizes a frame
    if (name, size) not in _fonts:
        _fonts[name, size] = ImageFont.truetype(os.path.join(HERE, "fonts", name), size)
    return _fonts[name, size]


F = {
    "city": font("InterDisplay-SemiBold.ttf", 60),
    "stat": font("InterDisplay-SemiBold.ttf", 44),
    "caps": font("Inter-SemiBold.ttf", 18),
    "blabel": font("Inter-Bold.ttf", 40),
    "apt": font("Inter-Bold.ttf", 26),
    "bstat": font("InterDisplay-Bold.ttf", 76),
    "bgo": font("InterDisplay-Bold.ttf", 52),
    "bcaps": font("Inter-Bold.ttf", 22),
    "bodym": font("Inter-Medium.ttf", 32),
    "small": font("Inter-Medium.ttf", 26),
    "label": font("Inter-Bold.ttf", 30),
    "tiny": font("Inter-SemiBold.ttf", 22),
}


# ---------- data ----------

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


class Cache:
    def __init__(self, path):
        self.path = path
        try:
            with open(path) as f:
                self.d = json.load(f)
        except (OSError, ValueError):
            self.d = {"route": {}, "airframe": {}}
        self.dirty = False

    def get(self, kind, key, ttl=None):
        hit = self.d.setdefault(kind, {}).get(key)
        if hit is None:
            return None
        if ttl is not None and time.time() - hit["t"] > ttl:
            return None
        return hit

    def put(self, kind, key, value):
        self.d.setdefault(kind, {})[key] = {"t": time.time(), "v": value}
        self.dirty = True

    def save(self):
        if not self.dirty:
            return
        # Keep the file from growing forever on a device that runs for months
        for kind in self.d:
            if len(self.d[kind]) > 3000:
                items = sorted(self.d[kind].items(), key=lambda kv: kv[1]["t"])
                self.d[kind] = dict(items[-2000:])
        if write_json(self.path, self.d):
            self.dirty = False


def fetch_aircraft(session):
    """Every aircraft near the map, each stamped with the epoch of its position fix.
    Nothing is filtered to the map here; project() does that for any moment in time."""
    nm = int(map_reach_km() / KM_PER_NM) + FETCH_MARGIN_NM
    for i, url in enumerate(ADSB_URLS):
        try:
            r = session.get(url.format(lat=HOME_LAT, lon=HOME_LON, nm=nm), timeout=15)
            r.raise_for_status()
            data = r.json()
            break
        except (requests.RequestException, ValueError):
            if i == len(ADSB_URLS) - 1:
                raise
    now = data.get("now") or time.time()
    now = now / 1000.0 if now > 1e11 else float(now)  # adsb.lol sends ms, adsb.fi seconds
    planes = []
    for a in data.get("ac", data.get("aircraft", [])):
        if "lat" not in a or "lon" not in a:
            continue
        alt = a.get("alt_baro")
        if alt == "ground" or alt is None:
            continue
        # Airport ground vehicles and towers squawk too; drop anything without a type or callsign
        callsign = (a.get("flight") or "").strip()
        reg = a.get("r") or ""
        if not callsign and not reg:
            continue
        planes.append({
            "hex": a.get("hex", ""),
            "callsign": callsign,
            "reg": reg,
            "name": reg if reg and callsign == reg.replace("-", "") else (callsign or reg),
            "type": a.get("t") or "",
            "alt": int(alt),
            "gs": a.get("gs"),
            "track": a.get("track", a.get("true_heading")),
            "rate": a.get("baro_rate", a.get("geom_rate")),
            "lat": a["lat"],
            "lon": a["lon"],
            "t": now - (a.get("seen_pos") or 0),
        })
    return planes


def project(planes, when, box=None):
    """Dead-reckon each plane to `when` along its track at its ground speed, with
    altitude following its vertical rate. Straight lines go wrong within minutes on
    approach turns, so fixes older than MAX_PROJECT_S are dropped rather than guessed.
    Returns copies filtered to `box` (default the map) and sorted nearest-first, with dist/brg set."""
    box = box or MAP_BOX
    out = []
    for p in planes:
        dt = when - p.get("t", when)
        if dt > MAX_PROJECT_S:
            continue
        q = dict(p)
        if dt > 0 and q["gs"] and q["track"] is not None:
            km = q["gs"] * KM_PER_NM * dt / 3600.0
            a = math.radians(q["track"])
            q["lat"] = p["lat"] + km * math.cos(a) / 110.57
            q["lon"] = p["lon"] + km * math.sin(a) / (111.32 * math.cos(math.radians(p["lat"])))
        if dt > 0 and q["rate"]:
            q["alt"] = int(p["alt"] + q["rate"] * dt / 60.0)
            if q["alt"] <= 0 and q["rate"] < 0:
                continue  # it has landed
            q["alt"] = max(0, q["alt"])
        x, y = to_px(q["lat"], q["lon"])
        if not (box[0] <= x <= box[2] and box[1] <= y <= box[3]):
            continue
        q["dist"], q["brg"] = distance_bearing(HOME_LAT, HOME_LON, q["lat"], q["lon"])
        out.append(q)
    out.sort(key=lambda p: p["dist"])
    return out


def lookup_route(session, cache, callsign):
    if not callsign:
        return None
    hit = cache.get("route2", callsign, ROUTE_TTL)
    if hit:
        return hit["v"]
    route = None
    try:
        r = session.get(ROUTE_URL.format(cs=callsign), timeout=8)
        if r.ok:
            fr = r.json().get("response", {})
            fr = fr.get("flightroute") if isinstance(fr, dict) else None
            if fr:
                o, d = fr.get("origin") or {}, fr.get("destination") or {}
                airline = fr.get("airline") or {}
                trusted = airline.get("icao") == callsign[:3]
                iata = fr.get("callsign_iata") or ""
                route = {
                    "airline": airline.get("name") if trusted else None,
                    "flight": "%s %s" % (iata[:2], iata[2:]) if trusted and iata[:2].isalnum() and not iata[:2].isdigit() and iata[2:].isdigit() else None,
                    "from": o.get("iata_code") or o.get("icao_code"),
                    "from_city": o.get("municipality"),
                    "from_ll": (o.get("latitude"), o.get("longitude")),
                    "to": d.get("iata_code") or d.get("icao_code"),
                    "to_city": d.get("municipality"),
                    "to_ll": (d.get("latitude"), d.get("longitude")),
                }
    except (requests.RequestException, ValueError):
        return None  # transient; don't cache
    cache.put("route2", callsign, route)
    return route


def clean_model(maker, kind):
    """'Hawker Beechcraft Corp' + 'King Air B350' -> 'Beechcraft King Air B350',
    'Airbus' + 'A321 271NXSL' -> 'Airbus A321'. Drops corporate suffixes and the
    sub-variant codes that follow the first numbered token."""
    junk = {"corp", "corporation", "inc", "co", "company", "ltd", "aircraft", "industries", "aerospace", "hawker"}
    words = [t for t in (maker or "").replace(",", " ").split() if t.lower().strip(".") not in junk]
    maker = " ".join(words[:2]) if words else ""
    kept = []
    for t in (kind or "").split():
        kept.append(t)
        if any(c.isdigit() for c in t):
            break
    kind = re.sub(r"^(\d{3})NG$", r"\1", " ".join(kept))
    return " ".join(x for x in (maker, kind) if x)


def lookup_airframe(session, cache, hexid):
    if not hexid:
        return None
    hit = cache.get("airframe2", hexid)
    if hit:
        return hit["v"]
    frame = None
    try:
        r = session.get(AIRFRAME_URL.format(hex=hexid), timeout=8)
        if r.ok:
            ac = r.json().get("response", {})
            ac = ac.get("aircraft") if isinstance(ac, dict) else None
            if ac:
                frame = {
                    "model": clean_model(ac.get("manufacturer"), ac.get("type")),
                    "owner": ac.get("registered_owner"),
                }
    except (requests.RequestException, ValueError):
        return None
    cache.put("airframe2", hexid, frame)
    return frame


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


def to_px(lat, lon):
    """Local equirectangular projection centered on home, HEADING up."""
    scale = (RADAR / 2) / RANGE_KM  # px per km
    ex = (lon - HOME_LON) * 111.32 * math.cos(math.radians(HOME_LAT))
    ny = (lat - HOME_LAT) * 110.57
    h = math.radians(HEADING)
    dx = ex * math.cos(h) - ny * math.sin(h)
    dy = ex * math.sin(h) + ny * math.cos(h)
    cx, cy = RADAR_X + RADAR / 2, RADAR_Y + RADAR / 2
    return cx + dx * scale, cy - dy * scale


def night_box():
    """The night view re-centers the day map in the whole visible area at the same scale:
    returns its x shift and the area it shows, in day-map pixels."""
    x0, y0, x1, y1 = SAFE
    dx = (x0 + x1) / 2.0 - (MAP_BOX[0] + MAP_BOX[2]) / 2.0
    return dx, (x0 - dx, y0, x1 - dx, y1)


def map_reach_km():
    """Distance from home to the farthest corner of the day map or the night view."""
    cx, cy = RADAR_X + RADAR / 2, RADAR_Y + RADAR / 2
    far = max(math.hypot(x - cx, y - cy) for box in (MAP_BOX, night_box()[1])
              for x in box[::2] for y in box[1::2])
    return far / ((RADAR / 2) / RANGE_KM)


def compass(brg):
    return ("N", "NE", "E", "SE", "S", "SW", "W", "NW")[int((brg + 22.5) // 45) % 8]


def alt_shade(alt):
    """Low and close reads black; cruising traffic fades toward gray."""
    t = max(0.0, min(1.0, (alt - 2000) / 33000))
    return int(INK + t * 85)


def fmt_alt(alt):
    if alt < 100:
        return "on runway"
    if alt >= 18000:
        return "FL%03d" % round(alt / 100)
    return "{:,} ft".format(int(round(alt, -2)))


# ---------- drawing ----------

_bbox, _glyphs = {}, {}


class CachedDraw(ImageDraw.ImageDraw):
    """ImageDraw that renders each (string, font) once and pastes it after that.
    FreeType rasterizing was half the Kindle's frame time, and minute to minute
    most strings (cities, labels, the flight) don't change."""

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


def halo_text(d, xy, s, f, fill, r=3):
    """Text with a paper-colored halo. Drawn by offsetting instead of stroke_width,
    which segfaults against the Kindle's FreeType."""
    x, y = xy
    for dx in (-r, 0, r):
        for dy in (-r, 0, r):
            if dx or dy:
                d.text((x + dx, y + dy), s, font=f, fill=PAPER)
    d.text(xy, s, font=f, fill=fill)


# Google Material Icons (Apache 2.0): top-down airplane that points north
ICON_FONT = os.path.join(HERE, "fonts", "MaterialIcons-Regular.ttf")
ICON_PLANE = "\ue539"
_icons = {}


def icon_mask(char, px):
    if (char, px) not in _icons:
        m = Image.new("L", (px, px), 0)
        ImageDraw.Draw(m).text((px / 2, px / 2), char, font=ImageFont.truetype(ICON_FONT, px), fill=255, anchor="mm")
        _icons[char, px] = m
    return _icons[char, px]


_turned = {}


def turned_icon(char, px, angle, halo):
    """Rotated mask and its halo, cached by 5 degree steps. The halo's MaxFilter was
    most of the Kindle's render time, and a plane's heading barely changes minute to minute."""
    step = int(round((angle or 0) / 5.0)) * 5 % 360
    key = (char, px, step, halo)
    if key not in _turned:
        if len(_turned) > 400:
            _turned.clear()
        m = icon_mask(char, px)
        if step:
            m = m.rotate(-step, resample=Image.BICUBIC, expand=True)
        _turned[key] = (m, m.filter(ImageFilter.MaxFilter(2 * halo + 1)) if halo else None)
    return _turned[key]


def draw_icon(img, char, x, y, px, fill, angle=0, halo=4):
    """Paste an icon centered on (x, y), turned clockwise by angle, with a paper halo."""
    m, rim = turned_icon(char, px, angle, halo)
    ox, oy = int(x - m.width / 2), int(y - m.height / 2)
    if rim is not None:
        img.paste(PAPER, (ox, oy), rim)
    img.paste(fill, (ox, oy), m)


def plane_glyph(img, x, y, track, size, fill):
    """Airplane pointing along track; size is roughly its half-length in pixels."""
    draw_icon(img, ICON_PLANE, x, y, int(size * 2.2), fill, angle=track or 0)


_lake = {}


def lake_box():
    """The map area run out to the panel's edges on the far sides: the frame's mat hides
    those edges, so the lake carries on under it instead of stopping short of the mat."""
    if STYLES[STYLE].get("map_side") == "right":
        return (MAP_BOX[0], 0, W, H)
    return (0, 0, MAP_BOX[2], H)


def lake_layer(shore, tint):
    """The lake and shoreline never move, so draw them once per layout and reuse. Home is
    in the key: config.json is re-read every frame, and a new home must move the lake too."""
    key = (tint, HEADING, HOME_LAT, HOME_LON, lake_box(), RADAR, RADAR_X, RADAR_Y)
    if key not in _lake:
        lake = Image.new("L", (W, H), PAPER)
        ld = ImageDraw.Draw(lake)
        for ring in shore:
            if len(ring) < 2:
                continue
            pts = [to_px(lat, lon) for lon, lat in ring]
            # Close the lake far to the south, in map space, so it survives any HEADING
            ld.polygon(pts + [to_px(42.0, -77.0), to_px(42.0, -81.5)], fill=tint)
            ld.line(pts, fill=FAINT, width=3, joint="curve")
        _lake.clear()
        _lake[key] = lake.crop(lake_box())
    return _lake[key]


def draw_radar(img, d, planes, shore, feat):
    st = STYLES[STYLE]
    cx, cy = RADAR_X + RADAR / 2, RADAR_Y + RADAR / 2
    scale = (RADAR / 2) / RANGE_KM

    img.paste(lake_layer(shore, st["lake"]), lake_box()[:2])

    if st["rings"]:
        for km in RINGS_KM:
            r = km * scale
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=FAINT, width=3)
            d.text((cx + 6, cy - r + 4), "%d km" % km, font=F["tiny"], fill=DIM)

    for code, lat, lon in AIRPORTS:
        x, y = to_px(lat, lon)
        d.rectangle((x - 5, y - 5, x + 5, y + 5), outline=DIM, width=2)
        d.text((x + 10, y - 12), code, font=F["tiny"], fill=DIM)

    if HEADING % 360:
        # North tick on the outer ring so a turned map still reads
        a = math.radians(-HEADING)
        r = RADAR / 2
        nx, ny = cx + math.sin(a) * r, cy - math.cos(a) * r
        d.ellipse((nx - 20, ny - 20, nx + 20, ny + 20), fill=PAPER, outline=DIM, width=2)
        d.text((nx - text_w(d, "N", F["label"]) / 2, ny - 15), "N", font=F["label"], fill=INK)

    if st["rings"]:
        d.ellipse((cx - 9, cy - 9, cx + 9, cy + 9), fill=INK)
        d.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), fill=PAPER)
    else:
        # Home is a plain crosshair so it reads as part of the map, not a marker on top of it
        r = 13
        d.line((cx - r, cy, cx + r, cy), fill=INK, width=3)
        d.line((cx, cy - r, cx, cy + r), fill=INK, width=3)

    # Place labels nearest-first so the closest planes win any collision
    # Home marker and airport labels are fixed; flight labels steer around them
    taken, labels = [(cx - 16, cy - 16, cx + 16, cy + 16)], {}
    for code, lat, lon in AIRPORTS:
        x, y = to_px(lat, lon)
        taken.append((x - 8, y - 14, x + 14 + text_w(d, code, F["tiny"]), y + 14))
    # The featured plane claims its label spot first, then nearest-first
    lf = F[st["label"]]
    order = ([feat] if feat else []) + [q for q in planes[:st["labeled"]] if q is not feat]
    order = order[:st["labeled"]]
    for p in order:
        i = id(p)
        x, y = to_px(p["lat"], p["lon"])
        size = st["feat_size"] if p is feat else st["size"]
        name, sub = p["name"], fmt_alt(p["alt"]) if st["sub"] else ""
        bw = max(text_w(d, name, lf), text_w(d, sub, F["tiny"]))
        lh = lf.size + (28 if sub else 0)
        for lx in (x + size + 8, x - size - 8 - bw):
            box = (lx - 4, y - lh // 2 - 4, lx + bw + 4, y + lh // 2 + 4)
            if box[2] > LABEL_BOX[2] or box[0] < LABEL_BOX[0] or box[1] < LABEL_BOX[1] or box[3] > LABEL_BOX[3]:
                continue
            if not any(box[0] < b[2] and b[0] < box[2] and box[1] < b[3] and b[1] < box[3] for b in taken):
                taken.append(box)
                labels[i] = (lx, name, sub)
                break

    # Draw far-to-near so the closest planes sit on top, and the featured one above all
    for p in [q for q in reversed(planes) if q is not feat] + ([feat] if feat else []):
        i = id(p)
        x, y = to_px(p["lat"], p["lon"])
        shade = alt_shade(p["alt"]) if st["sub"] or p is feat else FAINT
        size = st["feat_size"] if p is feat else st["size"]
        track = None if p["track"] is None else p["track"] - HEADING
        plane_glyph(img, x, y, track, size, INK if p is feat and not st["sub"] else shade)
        if i in labels:
            lx, name, sub = labels[i]
            lh = lf.size + (28 if sub else 0)
            halo_text(d, (lx, y - lh // 2 - lf.size // 8), name, lf, INK if p is feat else 60, r=max(3, lf.size // 8))
            if sub:
                halo_text(d, (lx, y - lh // 2 + lf.size + 2), sub, F["tiny"], DIM)


def fit_font(d, s, name, size, width, floor=34):
    """Largest size (stepping down) at which s fits the width."""
    while size > floor:
        f = font(name, size)
        if text_w(d, s, f) <= width:
            return f
        size -= 4
    return font(name, floor)


def fmt_dur(minutes):
    minutes = int(round(minutes))
    if minutes < 60:
        return "%dm" % minutes
    return "%dh %02dm" % (minutes // 60, minutes % 60)


def local_leg(p, route):
    """adsbdb lists the whole itinerary for multi-leg flight numbers (YUL-YYZ-YYJ comes
    back as YUL-YYJ). A plane low and near a Toronto airport is on the leg that starts
    or ends here, so swap Toronto in on the side its climb or descent implies."""
    if not route or p["alt"] > 15000:
        return route
    codes = [c for c, _, _ in AIRPORTS]
    if route.get("from") in codes or route.get("to") in codes:
        return route
    near = min(AIRPORTS, key=lambda a: distance_bearing(p["lat"], p["lon"], a[1], a[2])[0])
    if distance_bearing(p["lat"], p["lon"], near[1], near[2])[0] > 50:
        return route
    route = dict(route)
    side = "from" if (p["rate"] or 0) >= 0 else "to"
    route[side], route[side + "_city"], route[side + "_ll"] = near[0], LOCAL_CITY, (near[1], near[2])
    return route


def plausible(p, route):
    """adsbdb routes go stale when airlines reuse flight numbers. Drop any route whose
    detour through the plane's position is far longer than the direct path."""
    ends = tuple(route.get("from_ll") or (None,)) + tuple(route.get("to_ll") or (None,)) if route else ()
    if not route or None in ends:
        return route
    total, _ = distance_bearing(*ends)
    via = (distance_bearing(p["lat"], p["lon"], *route["from_ll"])[0]
           + distance_bearing(p["lat"], p["lon"], *route["to_ll"])[0])
    return route if via <= total * 1.2 + 80 else None


def progress(p, route):
    """Progress along the great circle, estimated from position and speed:
    (fraction flown, minutes flown, minutes left, km flown, km left, km total).

    There is no schedule data, so elapsed assumes ~720 km/h block speed plus 15 minutes
    of taxi and climb, and remaining uses current ground speed plus 10 minutes to land."""
    ends = tuple(route.get("from_ll") or (None,)) + tuple(route.get("to_ll") or (None,)) if route else ()
    if not route or None in ends:
        return None
    total, _ = distance_bearing(*ends)
    left, _ = distance_bearing(p["lat"], p["lon"], *route["to_ll"])
    if total < 50:
        return None
    flown = max(0.0, total - left)
    speed = max((p["gs"] or 0) * KM_PER_NM, 300)
    if left > 150:
        speed = max(speed, 780)  # still climbing out; it'll be at cruise for most of the way
    cruise = left / speed * 60
    # Far out, descent and landing add ~10 min; close in, the altitude still to lose
    # (about 1,500 ft a minute) is what sets the pace, plus a few minutes to touch down.
    to_go = cruise + 10 if left > 150 else max(cruise, p["alt"] / 1500.0) + 3
    return (min(1.0, flown / total),
            flown / 720 * 60 + (15 if flown > 5 else 0),
            to_go, flown, left, total)


def flight_line(p, route):
    """'Air Canada 891': airline name plus the flight number, falling back to the callsign."""
    airline = AIRLINES.get(p["callsign"][:3]) or (route or {}).get("airline")
    number = ((route or {}).get("flight") or "").split(" ")[-1]
    if not number and p["callsign"][3:].isdigit():
        number = p["callsign"][3:]
    if airline and number:
        return "%s %s" % (airline, number)
    return " · ".join(t for t in (airline, p["name"]) if t)


def enrich(session, cache, raw, now):
    """Routes and airframes for every plane that could be featured before the next
    fetch: the nearest few now and halfway to the next fetch. Wi-Fi is only up during
    a fetch, so anything needed later has to be looked up here."""
    want = []
    for t in (now, now + FETCH_S / 2):
        for p in project(raw, t)[:6]:
            if p["hex"] not in [q["hex"] for q in want]:
                want.append(p)
    routes, frames = {}, {}
    for p in want:
        r = plausible(p, local_leg(p, lookup_route(session, cache, p["callsign"])))
        if r:
            # adsbdb sometimes gives the district ("Arnavutköy, Istanbul"); keep the city
            r = dict(r, from_city=(r.get("from_city") or "").split(",")[-1].strip() or None,
                     to_city=(r.get("to_city") or "").split(",")[-1].strip() or None)
        routes[p["callsign"]] = r
        frames[p["hex"]] = lookup_airframe(session, cache, p["hex"])
    cache.save()
    return routes, frames


def fetch_interval(raw, routes, now):
    """10 minutes when the featured plane is cruising; 5 when it's low (turning onto
    approach or climbing out, where straight-line guesses go wrong fastest) or would
    leave the map before a 10-minute fetch; 15 when the sky is empty."""
    visible = project(raw, now)
    if not visible:
        return QUIET_FETCH_S
    feat = featured(visible, routes)
    if feat["alt"] < 10000:
        return FETCH_BUSY_S
    if not [p for p in project([r for r in raw if r["hex"] == feat["hex"]], now + FETCH_S)]:
        return FETCH_BUSY_S
    return FETCH_S


def airborne(p):
    """Flying and reporting speed. Planes on the runway (or with a bad altitude) report
    0 ft and no speed; they stay on the map but never take the panel."""
    return p["alt"] >= 100 and bool(p["gs"])


def featured(planes, routes):
    """The closest airborne plane, but a flight with a known route wins unless it is much
    farther away: a private jet with nothing to say shouldn't take the panel from an
    airliner a few km beyond it."""
    flying = [p for p in planes if airborne(p)] or planes
    first = flying[0]
    if routes.get(first["callsign"]):
        return first
    for q in flying[1:8]:
        if routes.get(q["callsign"]) and q["dist"] <= first["dist"] * 3 + 5:
            return q
    return first


def stat(d, x, y, value, label):
    d.text((x, y), value, font=F["stat"], fill=INK)
    d.text((x, y + 54), label, font=F["caps"], fill=DIM)


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


TRACKS_PATH = os.path.join(HERE, "tracks.json")
TRACKS = {"day": "", "pts": [], "hexes": []}


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


def day_key(when):
    """The traffic day runs from one morning to the next, so tonight shows today."""
    return time.strftime("%Y-%m-%d", time.localtime(next_morning(when) - 86400))


def load_tracks():
    global TRACKS
    try:
        with open(TRACKS_PATH) as f:
            TRACKS = json.load(f)
    except (OSError, ValueError):
        pass


def record_positions(planes, when):
    """Every plane's position at every draw, for the night-time constellation."""
    if TRACKS.get("day") != day_key(when):
        TRACKS.update(day=day_key(when), pts=[], hexes=[])
    TRACKS["pts"].extend([round(p["lat"], 4), round(p["lon"], 4)] for p in planes)
    seen = set(TRACKS["hexes"])
    TRACKS["hexes"].extend(p["hex"] for p in planes if p["hex"] not in seen)


def save_tracks():
    write_json(TRACKS_PATH, TRACKS, separators=(",", ":"))


def render_night(shore, tracks, note=None):
    """The day's traffic as a constellation: every sampled position a dark point on
    paper, darker where paths overlap, so the approach corridors draw themselves."""
    global CANVAS
    img = CANVAS = Image.new("L", (W, H), PAPER)
    d = CachedDraw(img)
    x0, y0, x1, y1 = SAFE
    dx = night_box()[0]

    def px(lat, lon):
        x, y = to_px(lat, lon)
        return x + dx, y

    for ring in shore:
        if len(ring) > 1:
            d.line([px(lat, lon) for lon, lat in ring], fill=FAINT, width=3, joint="curve")
    counts = {}
    for lat, lon in tracks.get("pts", []):
        x, y = px(lat, lon)
        if x0 + 6 <= x <= x1 - 6 and y0 + 6 <= y <= y1 - 52:
            key = (int(x) // 3, int(y) // 3)
            counts[key] = counts.get(key, 0) + 1
    for (bx, by), c in counts.items():
        v = max(0, int(100 - 45 * math.log(1 + c, 2)))
        cx, cy = bx * 3 + 1, by * 3 + 1
        d.ellipse((cx - 2.5, cy - 2.5, cx + 2.5, cy + 2.5), fill=v)
    hx, hy = px(HOME_LAT, HOME_LON)
    d.line((hx - 12, hy, hx + 12, hy), fill=INK, width=3)
    d.line((hx, hy - 12, hx, hy + 12), fill=INK, width=3)
    n = len(tracks.get("hexes", []))
    caption = "%d flights today" % n if n else "No flights recorded today"
    full = caption + ("   " + note if note else "")
    x0, y1 = TEXT[0], TEXT[3]
    d.rectangle((x0, y1 - 54, x0 + 24 + text_w(d, full, F["bodym"]), y1), fill=PAPER)
    d.text((x0 + 12, y1 - 46), caption, font=F["bodym"], fill=INK)
    if note:
        d.text((x0 + 12 + text_w(d, caption + "   ", F["bodym"]), y1 - 46), note, font=F["bodym"], fill=DIM)
    return img


TRAFFIC_PATH = os.path.join(HERE, "traffic.json")
BUCKET_S = 300
TRAFFIC = {}
STALE_SINCE = None  # "1:23" when the data is too old to project; set by Frame.render()


def load_traffic():
    global TRAFFIC
    try:
        with open(TRAFFIC_PATH) as f:
            TRAFFIC = json.load(f)
    except (OSError, ValueError):
        TRAFFIC = {}


def record_traffic(count, when):
    """Planes in the zone, one number per 5-minute bucket, keeping today and yesterday."""
    lt = time.localtime(when)
    day = time.strftime("%Y-%m-%d", lt)
    series = TRAFFIC.setdefault(day, [None] * (86400 // BUCKET_S))
    series[(lt.tm_hour * 3600 + lt.tm_min * 60) // BUCKET_S] = count
    for old in sorted(TRAFFIC)[:-2]:
        del TRAFFIC[old]
    write_json(TRAFFIC_PATH, TRAFFIC)


def _filled(series, upto, half=9):
    """Carry the last reading forward over gaps (quiet hours fetch less often), then a
    centered triangular mean over ~90 minutes so the shape reads as the day's rhythm,
    not 5-minute noise. At the live edge the window just runs out of future points."""
    held, last = [], None
    for v in series[:upto]:
        last = v if v is not None else last
        held.append(last)
    out = []
    for i in range(len(held)):
        num = den = 0.0
        for j in range(max(0, i - half), min(len(held), i + half + 1)):
            if held[j] is not None:
                wgt = half + 1 - abs(i - j)
                num += wgt * held[j]
                den += wgt
        out.append(num / den if den else None)
    return out


def draw_traffic(d, x, y, w, h, now):
    """Today's traffic as a quiet area, yesterday as a paler one behind it, a dot for now.
    Midnight to midnight across the full width, so position also reads as time of day."""
    today = time.strftime("%Y-%m-%d", now)
    days = sorted(TRAFFIC)
    yday = [k for k in days if k < today]
    nb = 86400 // BUCKET_S
    cur = (now.tm_hour * 3600 + now.tm_min * 60) // BUCKET_S
    t_series = _filled(TRAFFIC.get(today, [None] * nb), cur + 1)
    y_series = _filled(TRAFFIC[yday[-1]], nb) if yday else []
    vals = [v for v in t_series + y_series if v is not None]
    if not vals:
        return
    top = max(vals + [4])

    # Drawn at 3x and scaled down: Pillow doesn't antialias polygons, and e-ink shows
    # the staircase on a gentle curve
    k = 3
    plot = Image.new("L", (w * k, (h + 8) * k), PAPER)
    pd = ImageDraw.Draw(plot)
    pad = 4 * k

    def pts(series):
        return [(w * k * (i + 0.5) / nb, pad + h * k - h * k * v / top) for i, v in enumerate(series) if v is not None]

    pbase = pad + h * k
    ys = pts(y_series)
    if ys:
        pd.polygon([(ys[0][0], pbase)] + ys + [(ys[-1][0], pbase)], fill=236)
    ts = pts(t_series)
    if ts:
        pd.polygon([(ts[0][0], pbase)] + ts + [(ts[-1][0], pbase)], fill=FAINT_BAR)
        pd.line(ts, fill=DIM, width=2 * k, joint="curve")
    pd.line((0, pbase, w * k, pbase), fill=FAINT, width=k)
    CANVAS.paste(plot.resize((w, h + 8), Image.LANCZOS), (int(x), int(y - 4)))
    base = y + h
    if ts:
        nx, ny = x + ts[-1][0] / k, y - 4 + ts[-1][1] / k
        d.ellipse((nx - 6, ny - 6, nx + 6, ny + 6), fill=INK, outline=PAPER, width=2)

    # Labels: what it is on the left, today's peak on the right, three quiet time ticks
    d.text((x, y - 30), "TODAY", font=F["bcaps"], fill=DIM)
    raw = [v for v in TRAFFIC.get(today, [])[:cur + 1] if v is not None]
    if raw:
        pk = max(raw)
        i = TRAFFIC[today].index(pk)
        hh, mm = divmod(i * BUCKET_S // 60, 60)
        peak = "PEAK %d · %d:%02d%s" % (pk, hh % 12 or 12, mm, "A" if hh < 12 else "P")
        d.text((x + w - text_w(d, peak, F["bcaps"]), y - 30), peak, font=F["bcaps"], fill=DIM)
    for hr, lab in ((6, "6A"), (12, "12P"), (18, "6P")):
        tx = x + w * hr / 24.0
        d.text((tx - text_w(d, lab, F["caps"]) / 2, base + 4), lab, font=F["caps"], fill=FAINT)


def draw_panel_bold(d, planes, routes, frames, now, feat):
    """One flight, big: where it's going, how high and fast, how long left, who."""
    x, w = PANEL_X, PANEL_R - PANEL_X
    top, bottom = TEXT[1], TEXT[3]
    face = "InterDisplay-Bold.ttf"
    if not feat:
        # An outage must never pass for an empty sky
        y = top
        for ln, f in wrap(d, "Offline" if STALE_SINCE else "Quiet skies", face, 96, w):
            d.text((x, y), ln, font=f, fill=INK)
            y += f.size + 6
        if STALE_SINCE:
            d.text((x, y + 10), "No data since " + STALE_SINCE, font=F["bgo"], fill=DIM)
        if STYLES[STYLE].get("chart"):
            draw_traffic(d, x, bottom - 40 - 120, w, 120, now)
        return
    p = feat
    route = routes.get(p["callsign"])
    model = (frames.get(p["hex"]) or {}).get("model") or p["type"]

    # Headline: the city pair, wrapped big; with no route the aircraft is the story
    if route and route.get("from_city") and route.get("to_city"):
        # Non-breaking space keeps the arrow on the destination's first line
        blocks = [(route["from_city"], INK), ("→\u00a0" + route["to_city"], INK)]
    else:
        blocks = [(model or p["name"], INK)]
    lines = [(ln, f, fill) for text, fill in blocks for ln, f in wrap(d, text, face, 96, w)]
    size = 96 if len(lines) <= 3 else 80
    if size != 96:
        lines = [(ln, f, fill) for text, fill in blocks for ln, f in wrap(d, text, face, size, w)]
    y = top - 6
    for ln, f, fill in lines:
        d.text((x, y), ln, font=f, fill=fill)
        y += f.size + 4
    y += 30

    # Height and speed
    alt = "{:,}".format(int(round(p["alt"], -2))) if p["alt"] >= 100 else "0"
    spd = "{:,}".format(int(round(p["gs"] * KM_PER_NM))) if p["gs"] else "—"
    sf = F["bstat"]
    while sf.size > 52 and max(text_w(d, alt, sf), 170) + 44 + text_w(d, spd, sf) > w:
        sf = font("InterDisplay-Bold.ttf", sf.size - 4)
    d.text((x, y), alt, font=sf, fill=INK)
    d.text((x + 2, y + sf.size + 10), "FEET", font=F["apt"], fill=INK)
    sx = x + max(text_w(d, alt, sf), 170) + 44
    d.text((sx, y), spd, font=sf, fill=INK)
    d.text((sx + 2, y + sf.size + 10), "KM/H", font=F["apt"], fill=INK)
    y += 150

    # Progress: a flight path, solid where it has been, lighter ahead, the plane on it
    prog = progress(p, route)
    flight_y = bottom - 50
    if prog and y + 150 <= flight_y:
        frac, flown, left, km_flown, km_left, km_total = prog
        y += 14
        ly = y + 10
        fx = x + 22 + int((w - 44) * frac)
        d.line((fx, ly, x + w, ly), fill=FAINT_BAR, width=5)
        d.line((x, ly, fx, ly), fill=INK, width=5)
        d.ellipse((x - 1, ly - 7, x + 13, ly + 7), fill=INK)
        d.ellipse((x + w - 14, ly - 7, x + w, ly + 7), outline=INK, width=3, fill=PAPER)
        draw_icon(CANVAS, ICON_PLANE, fx, ly, 46, INK, angle=90, halo=6)
        d.text((x, y + 40), route["from"] or "", font=F["apt"], fill=INK)
        code = route["to"] or ""
        d.text((x + w - text_w(d, code, F["apt"]), y + 40), code, font=F["apt"], fill=INK)
        # Whichever side of the trip is longer is the more telling number
        if left < 4:
            rem = "Landing"
        elif flown > left:
            rem = fmt_dur(flown) + " flown"
        else:
            rem = fmt_dur(left) + " to go"
        d.text((x, y + 80), rem, font=F["bgo"], fill=INK)
        y += 150

    fl = flight_line(p, route) if route else p["name"]
    ff = fit_font(d, fl, "Inter-SemiBold.ttf", 40, w, floor=28)
    if STYLES[STYLE].get("chart"):
        # The flight line belongs to the flight, so it follows the progress block; the day's
        # trend is separate context and sits last, only if there's room left for it
        d.text((x, y), fit(d, fl, ff, w), font=ff, fill=70)
        y += ff.size + 24
        ch = 84
        cy = bottom - 24 - ch
        if cy - 30 >= y + 12:
            draw_traffic(d, x, cy, w, ch, now)
    else:
        d.text((x, bottom - 10 - ff.size), fit(d, fl, ff, w), font=ff, fill=70)


def draw_panel(d, planes, routes, frames, now, feat):
    """Right-hand column, in reading order of interest: where it's going, how it's
    flying, how far along it is, then who it is."""
    x, w = PANEL_X, PANEL_R - PANEL_X
    top, bottom = TEXT[1], TEXT[3]
    # Count and clock sit in the map's empty top-left corner
    d.text((MAP_BOX[0] + 12, top + 8), "%d aircraft" % len(planes), font=F["bodym"], fill=INK)
    d.text((MAP_BOX[0] + 12, top + 46), time.strftime("%-I:%M", now), font=F["small"], fill=DIM)

    if not planes:
        d.text((x, top + 20), "Offline" if STALE_SINCE else "Quiet skies.", font=F["city"], fill=DIM)
        return

    p = feat
    route = routes.get(p["callsign"])
    frame = frames.get(p["hex"])
    model = (frame or {}).get("model") or p["type"]

    # 1. City to city, as large as the column allows
    y = top + 4
    if route and route.get("from_city") and route.get("to_city"):
        a, b, bfill = route["from_city"], "→ " + route["to_city"], INK
    else:
        a, b, bfill = p["name"], "Route unknown", DIM
    f = fit_font(d, max(a, b, key=lambda t: text_w(d, t, F["city"])), "InterDisplay-SemiBold.ttf", 56, w)
    d.text((x, y), fit(d, a, f, w), font=f, fill=INK)
    d.text((x, y + f.size + 6), fit(d, b, f, w), font=f, fill=bfill)
    y += 2 * f.size + 40

    # 2. Height, speed, heading
    stats = (("{:,}".format(int(round(p["alt"], -2))) if p["alt"] >= 100 else "0", "FEET"),
             ("%d" % round(p["gs"] * KM_PER_NM) if p["gs"] else "—", "KM/H"),
             (compass(p["track"]) if p["track"] is not None else "—", "HEADING"))
    widths = [max(text_w(d, v, F["stat"]), text_w(d, l, F["caps"])) for v, l in stats]
    gap = max(24, (w - sum(widths)) // 2)
    sx = x
    for (value, label), sw in zip(stats, widths):
        stat(d, sx, y, value, label)
        sx += sw + gap
    y += 104

    # 3. Elapsed and remaining, on a progress bar whose ends are the airport codes
    prog = progress(p, route)
    if prog:
        frac, flown, left, km_flown, km_left, km_total = prog
        d.text((x, y), route["from"] or "", font=F["caps"], fill=DIM)
        code = route["to"] or ""
        d.text((x + w - text_w(d, code, F["caps"]), y), code, font=F["caps"], fill=DIM)
        total = "{:,} KM".format(int(round(km_total)))
        d.text((x + (w - text_w(d, total, F["caps"])) // 2, y), total, font=F["caps"], fill=DIM)
        by = y + 36
        d.rounded_rectangle((x, by, x + w, by + 10), radius=5, fill=FAINT_BAR)
        fx = x + max(10, int(w * frac))
        d.rounded_rectangle((x, by, fx, by + 10), radius=5, fill=INK)
        d.ellipse((fx - 11, by - 6, fx + 11, by + 16), fill=INK, outline=PAPER, width=3)
        done = "Just departed" if flown < 15 else fmt_dur(flown) + " flown"
        rem = "Landing" if left < 4 else fmt_dur(left) + " to go"
        tf = F["bodym"] if text_w(d, done + rem, F["bodym"]) < w - 24 else F["small"]
        d.text((x, by + 28), done, font=tf, fill=INK)
        d.text((x + w - text_w(d, rem, tf), by + 28), rem, font=tf, fill=INK)
        a = "{:,} km".format(int(round(km_flown)))
        b = "{:,} km".format(int(round(km_left)))
        d.text((x, by + 66), a, font=F["small"], fill=DIM)
        d.text((x + w - text_w(d, b, F["small"]), by + 66), b, font=F["small"], fill=DIM)
        y = by + 116
    else:
        y += 10

    # 4-6. Flight number, airline, aircraft
    d.text((x, y), fit(d, flight_line(p, route), F["bodym"], w), font=F["bodym"], fill=INK)
    y += 40
    if model:
        d.text((x, y), fit(d, model, F["small"], w), font=F["small"], fill=DIM)
        y += 34
    y += 26

    # Also nearby: city pair first, the rest quiet
    for q in [q for q in planes if q is not p][:5]:
        if y > bottom - 72:
            break
        r = routes.get(q["callsign"])
        qm = (frames.get(q["hex"]) or {}).get("model") or q["type"]
        head = "%s → %s" % (r["from_city"], r["to_city"]) if r and r.get("from_city") and r.get("to_city") else (qm or q["name"])
        d.text((x, y), fit(d, head, F["bodym"], w), font=F["bodym"], fill=INK)
        d.text((x, y + 38), "%s  ·  %s  ·  %.0f km" % (q["name"], fmt_alt(q["alt"]), q["dist"]), font=F["small"], fill=DIM)
        y += 80


def render(planes, routes, frames, shore, now=None):
    global CANVAS
    img = CANVAS = Image.new("L", (W, H), PAPER)  # panels paste icons onto it
    d = CachedDraw(img)
    now = now or time.localtime()
    feat = featured(planes, routes) if planes else None
    draw_radar(img, d, planes, shore, feat)
    (draw_panel_bold if STYLE.startswith("bold") else draw_panel)(d, planes, routes, frames, now, feat)
    # No posterize step: the e-ink controller quantizes to its 16 levels itself, and it cost 40 ms
    return img


LAST_CFG = None


def load_config(args):
    """config.json beside this file overrides the defaults above; flags override config.json.
    Re-read every frame, so editing the file changes the display without a restart."""
    global HEADING, ROTATE, HOME_LAT, HOME_LON, LOCAL_CITY, AIRPORTS, STYLE, POWER, NIGHT, FRONTLIGHT, PANEL_W_CFG, INSET
    global LAST_CFG
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
    LOCAL_CITY = cfg.get("city", LOCAL_CITY)
    AIRPORTS = tuple(tuple(a) for a in cfg.get("airports", AIRPORTS))
    STYLE = cfg.get("style", STYLE) if cfg.get("style") in STYLES else STYLE
    POWER = cfg.get("power", {})
    NIGHT = tuple(cfg.get("night", NIGHT))  # ["23:00", "07:00"]
    if cfg.get("tz"):
        # POSIX form ("PST8PDT,M3.2.0,M11.1.0"): the Kindle has no zoneinfo to look names up in
        os.environ["TZ"] = cfg["tz"]
        time.tzset()
    FRONTLIGHT = int(cfg.get("frontlight", FRONTLIGHT))
    PANEL_W_CFG = cfg.get("panel_w")
    INSET = int(cfg.get("inset", 12))
    if args.heading is not None:
        HEADING = args.heading
    if args.rotate is not None:
        ROTATE = args.rotate
    if args.style:
        STYLE = args.style
    apply_layout(cfg.get("safe") or SAFE)  # after STYLE: the panel width depends on it
    return dict(power=POWER, rotate=ROTATE, style=STYLE, frontlight=FRONTLIGHT)


class Frame:
    """The planes frame for loop.run: ADS-B every 5 to 15 minutes, positions dead-reckoned
    in between so the planes move each minute, and the day's traffic as a constellation
    at night."""

    def __init__(self, args):
        self.args, self.log = args, {}
        with open(os.path.join(HERE, "shore.json")) as f:
            self.shore = json.load(f)
        self.cache = Cache(CACHE_PATH)
        self.raw, self.routes, self.frames = [], {}, {}
        load_traffic()
        load_tracks()

    def configure(self, args):
        return load_config(args)

    def fetch(self, session, now):
        self.raw = fetch_aircraft(session)
        self.routes, self.frames = enrich(session, self.cache, self.raw, now)
        record_traffic(len(project(self.raw, now)), now)
        save_tracks()
        if self.args.save_sample:
            with open(self.args.save_sample, "w") as f:
                json.dump({"planes": project(self.raw, now), "routes": self.routes, "frames": self.frames}, f, indent=1)

    @property
    def fetch_log(self):
        return {"planes": len(self.raw)}

    def fetch_every(self, now):
        return fetch_interval(self.raw, self.routes, now)

    def render(self, now, fetched_at):
        global STALE_SINCE
        visible = project(self.raw, now)
        # The night view spans the whole screen, wider than the day map beside the panel
        record_positions(project(self.raw, now, night_box()[1]), now)
        stale = now - fetched_at > MAX_PROJECT_S
        STALE_SINCE = time.strftime("%-I:%M", time.localtime(fetched_at)) if stale and fetched_at else None
        self.log = {"planes": len(visible)}
        return render(visible, self.routes, self.frames, self.shore)

    def moving(self, now):
        return bool(project(self.raw, now))

    def in_night(self, now):
        return in_night(now)

    def next_morning(self, now):
        return next_morning(now)

    def night_key(self, now, mode):
        return mode + day_key(now)

    def render_night(self, now, mode):
        img = render_night(self.shore, TRACKS, note="Battery low" if mode == "low" else None)
        self.log = {"points": len(TRACKS["pts"]), "flights": len(TRACKS["hexes"])}
        save_tracks()
        return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="render one frame and exit")
    ap.add_argument("--out", help="write PNG here instead of pushing to the screen")
    ap.add_argument("--heading", type=float, help="compass direction the viewer faces (0-359)")
    ap.add_argument("--rotate", type=int, choices=(0, 90, 180, 270), help="clockwise turn onto the panel")
    ap.add_argument("--style", choices=sorted(STYLES), help="override the config's style")
    ap.add_argument("--sample", help="render from a saved {planes, routes, frames} JSON instead of the network")
    ap.add_argument("--night", action="store_true", help="with --sample: render the night constellation")
    ap.add_argument("--save-sample", help="also write the fetched data to this JSON (for design testing)")
    ap.add_argument("--panel", help="preview another Kindle's panel, portrait WxH (758x1024 for a PW2)")
    ap.add_argument("--config", help="read this instead of the config.json beside planes.py")
    args = ap.parse_args()
    if args.panel:
        loop.PANEL = tuple(int(v) for v in args.panel.split("x"))
    load_config(args)

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    if args.sample:
        with open(os.path.join(HERE, "shore.json")) as f:
            shore = json.load(f)
        with open(args.sample) as f:
            data = json.load(f)
        TRAFFIC.update(data.get("traffic", {}))
        if args.night:
            img = render_night(shore, data.get("tracks", {}))
        else:
            img = render(data["planes"], data["routes"], data["frames"], shore,
                         now=time.strptime(data.get("time", "2026-09-24 16:40"), "%Y-%m-%d %H:%M"))
        path = args.out or "/tmp/planes.pgm"
        loop.turn(img, ROTATE).save(path)
        print(path)
        return

    loop.run(Frame(args), args)


if __name__ == "__main__":
    sys.exit(main())
