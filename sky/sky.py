#!/usr/bin/env python3
"""The sky frame: everything above the house. The sky as a map seen from above: straight
overhead in the middle, the horizon at the rim, the way you face (config "heading") at
the top. On it the nearest weather balloon, the ISS, Tiangong and
fresh Starlink trains, the Moon, planets and the brightest stars; beside it a headline for
the one thing worth looking up for, and in quiet moments a key of how far away each is.

Data: satellite orbits from CelesTrak once a day, and balloons from SondeHub around the
twice-daily launches (Buffalo's, from Toronto) and every few hours. Wi-Fi goes on only for those. The Sun, Moon, planets and
stars are computed on the device, so the sky still draws with no network at all.

Preview:  python sky/sky.py --sample sky/samples/night.json --rotate 0 --out out/sky.png
Run:      python sky/sky.py   (run.sh starts it, and the boot job starts run.sh)
"""

import argparse
import calendar
import csv
import io
import json
import math
import os
import time

import astro
import base
import icons
import loop
import requests
from PIL import Image, ImageChops, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
KM_PER_LY = 9.4607e12
with open(os.path.join(HERE, "stars", "stars.json")) as _f:
    SKY = json.load(_f)
# IBM Plex Serif for headlines and numbers, Plex Sans for names: technical and bookish at
# once, and its blunt serifs hold up on e-ink where fine ones break apart
TF = dict(head="IBMPlexSerif-Bold.ttf", num="IBMPlexSerif-Bold.ttf", name="IBMPlexSans-Bold.ttf",
          light="IBMPlexSans-SemiBold.ttf", scale=1.0)


def face(role, size):
    return base.font(TF[role], int(round(size * TF["scale"])))


def px(size):
    return int(round(size * TF["scale"]))


# Read from across a kitchen: nothing under 34 px (3 mm on the panel)
LABEL = face("name", 44)
BLABEL = face("name", 52)
RUNG = face("name", 40)
CAPS = face("name", 34)
SMALL = face("name", 34)
KM = face("light", 34)
NOTE = face("light", 34)
COMPASS = face("name", 46)
NUM = face("num", 104)
SKY_PANEL_W = 500
# Things down to this far below the horizon show outside the dome as ghosts
BELOW = 30
# Always a dark page, day and night, and light is importance: each step up the panel's 16
# grays pulls the eye harder. The one thing worth looking up for is white; everything else
# in the sky a step down; the text that supports it below that; structure (the horizon,
# rails, paths) recedes, thick but dimmer. E-ink's black is a dark gray, so
# the bottom half of the range sinks into it: every level sits in the top half. Multiples
# of 17 are the panel's own levels, so none of them get rounded.
HERO, THING, SOFT, FRAME, GROUND = 255, 238, 204, 153, 0


# ---------- where things are ----------

def dome_xy(el, az):
    """The sky as a map seen from above: straight overhead at the
    center, the horizon at the rim, and the direction you face (config "heading") at the
    top, with your left on the left. Not mirrored as a chart held overhead would be: a map
    is what people already read, and forward is up on it."""
    r = DOME_R * (90 - el) / 90
    a = math.radians(az - base.HEADING)
    return DOME_X + r * math.sin(a), DOME_Y - r * math.cos(a)


def seen_from_home(lat, lon, alt_km):
    """Elevation, azimuth and straight-line km to something at a height, allowing for the
    curve of the Earth (it drops 1.3 km over the horizon at the balloon's 130 km)."""
    dist, brg = base.distance_bearing(base.HOME_LAT, base.HOME_LON, lat, lon)
    rise = alt_km - dist * dist / (2 * 6371)
    return math.degrees(math.atan2(rise, max(dist, 0.01))), brg, math.hypot(dist, alt_km)


def mag_limit(sun_el):
    """Faintest star worth drawing: none in daylight, down to 2.5 by astronomical dark. That
    keeps the ~90 stars that make the shapes people know, not the thousand a dark sky has."""
    if sun_el > -5:
        return None
    return 1.5 + 1.0 * min(1.0, (-5 - sun_el) / 12)


# Slow-changing work kept between frames: the Kindle redraws every minute, but satellite
# passes, rise and set times and the star field barely move in that time
_kept = {}


def kept(key, t, version, max_age, make, ends=None):
    """make() once and reuse it until `version` changes, it's `max_age` seconds old, the
    clock goes backwards, or `ends(value)` (when what it found is over) has passed."""
    hit = _kept.get(key)
    if (hit is None or hit[0] != version or not 0 <= t - hit[1] <= max_age
            or (ends and hit[2] is not None and ends(hit[2]) < t)):
        hit = _kept[key] = (version, t, make())
    return hit[2]


def build(data, t):
    lat, lon = base.HOME_LAT, base.HOME_LON
    sky = {"t": t, "sun_el": astro.sun_alt(t, lat, lon), "things": [], "clouds": data.get("clouds")}
    add = sky["things"].append

    # Nothing old shown as live: a weather balloon that's down (fresh_balloon), a pico unheard
    # for 2 hours has drifted off. Nor anything under a degree up: below the horizon it can't
    # be seen, and just above it it's lost in the haze (and "0°" reads as a mistake)
    b = data.get("balloon") if fresh_balloon(data.get("balloon"), t) else None
    if b:
        _, lat_b, lon_b, alt_m = b["track"][-1]
        el, az, rng = seen_from_home(lat_b, lon_b, alt_m / 1000)
    if b and el >= 1:
        # Burst once it's 300 m below the highest it got, or 100 m down since the last fix, or
        # its sonde says it's dropping (first heard already falling). Mostly its own heights:
        # not every sonde reports a vertical speed, and GPS height wanders a little
        fixes = b["track"]
        falling = peak_alt(b) - alt_m >= 300 or (len(fixes) > 1 and fixes[-2][3] - alt_m >= 100) \
            or (b.get("vel_v") or 0) < -3
        add(dict(kind="balloon", name="Weather balloon", el=el, az=az, km=rng, alt_km=alt_m / 1000,
                 rising=not falling, track=b["track"]))

    pico = data.get("amateur")
    if pico and t - pico.get("when", 0) < 7200:
        el, az, rng = seen_from_home(pico["lat"], pico["lon"], pico["alt"] / 1000)
        if el >= 1:
            # A pico balloon, in plain words: a small one radio hobbyists send round the world
            add(dict(kind="pico", name="Hobby balloon", el=el, az=az, km=rng,
                     alt_km=pico["alt"] / 1000, days=pico.get("days")))

    def moon_el(tt):
        return astro.moon_alt_az(tt, lat, lon)[0]

    def planet_el(name):
        return lambda tt: astro.alt_az(*astro.planet(name, tt)[:2], tt, lat, lon)[0]

    def sun_el(tt):
        return astro.sun_alt(tt, lat, lon)

    def below(th, el_at):
        """Mark something under the horizon as a ghost, with when it comes up."""
        if th["el"] > 0:
            return th
        th["below"] = True
        th["rises"] = kept(("rises", th["name"]), t, None, 3600, lambda: crossing(el_at, t, rising=True),
                           ends=lambda when: when)
        return th

    # The Moon whenever it's up or rises within the day: a rising Moon is a headline in waiting
    ma, mz, mdist, frac, waxing = astro.moon_alt_az(t, lat, lon)
    moon = below(dict(kind="moon", name="Moon", el=ma, az=mz, km=mdist, frac=frac, waxing=waxing), moon_el)
    if not moon.get("below") or moon.get("rises"):
        if moon.get("rises"):
            moon["rise_az"] = astro.moon_alt_az(moon["rises"], lat, lon)[1]
        add(moon)
    for name in astro.PLANETS:
        if sky["sun_el"] > -5 and name != "Venus":
            continue  # the rest wash out in daylight
        ra, dec, dist = astro.planet(name, t)
        el, az = astro.alt_az(ra, dec, t, lat, lon)
        if el > -BELOW:
            # Venus by day is there for whoever knows where to look: only where it has room
            add(below(dict(kind="planet", name=name, el=el, az=az, km=dist, extra=sky["sun_el"] > -5),
                      planet_el(name)))
    if sky["sun_el"] > -BELOW:
        ra, dec, _ = astro.sun(t)
        el, az = astro.alt_az(ra, dec, t, lat, lon)
        add(below(dict(kind="sun", name="Sun", el=el, az=az, km=astro.AU_KM), sun_el))

    # The space stations, and the newest Starlink launch while it's still a train of
    # lights (the sample carries only that group); every other satellite was clutter
    orbits = data.get("orbits") or data.get("tle", "")
    sats = kept("sats", t, orbits, 86400, lambda: split_orbits(astro.read_orbits(orbits)))
    for name, sat in sats["stations"]:
        look = astro.sat_look(sat, t, lat, lon)
        # Only when you could see it: sunlit, against a sky dark enough
        if look and look[0] >= 10 and look[4] and sky["sun_el"] < -6:
            add(dict(kind="station", name="ISS" if name.startswith("ISS") else "Tiangong",
                     el=look[0], az=look[1], km=look[2], lit=look[4]))
    # Pass searches are the costly part: redo them every half hour or once a pass is over
    sky["passes"] = []
    for name, sat in sats["stations"]:
        short = "ISS" if name.startswith("ISS") else "Tiangong"
        # Three days ahead, so a week without evening passes still has one to promise. The
        # answer only changes with new orbits, so it's kept until the pass is over
        ps = kept(("pass", short), t, orbits, 6 * 3600,
                  lambda sat=sat: astro.next_visible_pass(sat, t, lat, lon, span=3 * 86400),
                  ends=lambda ps: ps["set"])
        if ps:
            sky["passes"].append((short, ps))
    sky["pass"] = next((ps for name, ps in sky["passes"] if name == "ISS"), None)
    # A train is only seen against a dark sky: no search in daylight, half the frame's work
    sky["train"] = tr = kept("train", t, orbits, 600,
                             lambda: train_pass(sats["fleet"], t, lat, lon) if sky["sun_el"] < -3 else None,
                             ends=lambda tr: tr["end"])
    if tr and tr["start"] - 60 <= t <= tr["end"] and sky["sun_el"] < -6:
        # Only while a train is crossing is it worth placing each satellite
        for sat in sats["fleet"]:
            look = astro.sat_look(sat, t, lat, lon)
            if look and look[0] >= 10 and look[4]:
                add(dict(kind="train", name="Starlink", el=look[0], az=look[1], km=look[2]))

    if not moon.get("below"):
        moon["sets"] = kept("moonset", t, None, 3600, lambda: crossing(moon_el, t, rising=False),
                            ends=lambda when: when)

    # The Sun's day: today's, yesterday's length for the change, tomorrow's rise for the night.
    # The days either side by the calendar, at noon: 24 hours off is the wrong day across a
    # change of clocks
    lt = time.localtime(t)

    def noon(k):
        return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + k, 12, 0, 0, 0, 0, -1))
    days = kept("days", t, time.strftime("%Y-%m-%d", lt), 86400,
                lambda: (sun_day(t), sun_day(noon(-1)), sun_day(noon(1))))
    sky["day"], sky["yesterday"], sky["tomorrow"] = days
    sky["year"] = kept("year", t, lt.tm_year, 30 * 86400, lambda: year_of_days(lt.tm_year, lat))
    return sky


def split_orbits(orbits):
    return {"stations": [(n, s) for n, s in orbits if n.startswith(("ISS", "CSS"))],
            "fleet": [s for n, s in orbits if n.startswith("STARLINK")]}


def train_pass(fleet, t, lat, lon):
    """A fresh Starlink launch strings out along one orbit, so the satellites cross the
    same path one after another over several minutes. Summarise the pass that's on now
    or starts within 15 minutes: how many you'll see, from when to when, and the path."""
    seen = [ps for ps in (astro.next_pass(sat, t, lat, lon, span=1800, step=30) for sat in fleet)
            if ps and ps["visible"] and ps["rise"] <= t + 900]
    if len(seen) < 3:
        return None
    # Draw the path of the one that's highest right now (else the next one up): later
    # members cross a little to the side as the Earth turns under them
    def now_el(ps):
        k = min(ps["track"], key=lambda k: abs(k[0] - t))
        return k[1] if abs(k[0] - t) <= 30 else -90
    lead = max(seen, key=now_el) if any(now_el(ps) > -90 for ps in seen) else min(seen, key=lambda ps: ps["rise"])
    return dict(n=len(seen), start=min(ps["rise"] for ps in seen), end=max(ps["set"] for ps in seen),
                track=lead["track"], rise_az=lead["rise_az"], set_az=lead["set_az"], peak_el=lead["peak_el"])


SUN_HORIZON = -0.833  # refraction and the Sun's half-width: the almanac's sunrise and sunset


def sun_day(day_t):
    """The Sun's day, for the local calendar day of `day_t`: sunrise and sunset to the minute,
    their azimuths, and the arc between as (t, el, az) every 5 minutes."""
    lat, lon = base.HOME_LAT, base.HOME_LON
    lt = time.localtime(day_t)
    t0 = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    step = 300
    rise = sets = prev = None
    arc = []
    # The sunset that ends this day's sunrise: far north in summer it comes after midnight,
    # so the search runs on into the next morning
    for k in range((86400 + 6 * 3600) // step + 1):
        tt = t0 + k * step
        ra, dec, _ = astro.sun(tt)
        el, az = astro.alt_az(ra, dec, tt, lat, lon)
        if prev:
            if prev[1] <= SUN_HORIZON < el and rise is None and tt <= t0 + 86400:
                rise = prev[0] + step * (SUN_HORIZON - prev[1]) / (el - prev[1])
            if prev[1] > SUN_HORIZON >= el and rise is not None:
                sets = prev[0] + step * (prev[1] - SUN_HORIZON) / (prev[1] - el)
                break
        if rise is not None and el > SUN_HORIZON:
            arc.append((tt, el, az))
        prev = (tt, el)
    if not (rise and sets):
        return None

    def az_at(tt):
        ra, dec, _ = astro.sun(tt)
        return astro.alt_az(ra, dec, tt, lat, lon)[1]

    # Dark enough for stars: the Sun 12 degrees down, after sunset
    dark = next((tt for tt in range(int(sets), int(sets) + 4 * 3600, 300) if astro.sun_alt(tt, lat, lon) < -12), None)
    return dict(rise=rise, set=sets, rise_az=az_at(rise), set_az=az_at(sets), arc=arc, length=sets - rise, dark=dark)


def day_length_h(tt, lat):
    """Hours of daylight on the day of `tt`, from the Sun's declination alone: the almanac's
    formula, good to a minute, for the year's curve."""
    dec = math.radians(astro.sun(tt)[1])
    lat = math.radians(lat)
    x = (math.sin(math.radians(SUN_HORIZON)) - math.sin(lat) * math.sin(dec)) / (math.cos(lat) * math.cos(dec))
    return 2 * math.degrees(math.acos(max(-1.0, min(1.0, x)))) / 15


def year_of_days(year, lat):
    """[(day of year, hours of daylight)] every 4 days: the shape of the year."""
    jan1 = time.mktime((year, 1, 1, 12, 0, 0, 0, 0, -1))
    return [(doy, day_length_h(jan1 + (doy - 1) * 86400, lat)) for doy in range(1, 367, 4)]


def crossing(el_at, t, rising, span=18 * 3600, step=120):
    """When something next rises over (or sets below) the horizon, to two minutes."""
    return next((tt for tt in range(int(t), int(t) + span, step) if (el_at(tt) > 0) == rising), None)


# ---------- drawing ----------

def star_level(mag):
    return THING if mag < 1.5 else SOFT


def star_dot(img, d, x, y, mag, fill):
    if mag < 0.6:
        # The handful of brightest stars twinkle
        icons.paste(img, icons.glyph("sparkle", 24, fill), x, y, 0)
        return
    r = max(2.0, 6.4 - mag * 1.2)
    d.ellipse((x - r, y - r, x + r, y + r), fill=fill)


def inside(x, y, pad=0):
    return math.hypot(x - DOME_X, y - DOME_Y) <= DOME_R - pad


def star_layer(t, limit, star_fill):
    """The stars on black, for lightening onto the night dome. No constellation lines: at a
    size that reads across a room there's no space for them beside the labels. The sky
    turns a quarter degree a minute (about a pixel here), so this is redrawn every ten."""
    lat, lon = base.HOME_LAT, base.HOME_LON
    # Only the dome's square, not the whole page
    ox, oy = DOME_X - DOME_R, DOME_Y - DOME_R
    layer = Image.new("L", (2 * DOME_R + 1, 2 * DOME_R + 1), 0)
    d = ImageDraw.Draw(layer)
    pos = {}

    def xy(ra, dec):
        k = (ra, dec)
        if k not in pos:
            el, az = astro.alt_az(ra, dec, t, lat, lon)
            pos[k] = None
            if el > 0:
                x, y = dome_xy(el, az)
                pos[k] = (x - ox, y - oy)
        return pos[k]

    for ra, dec, mag in SKY["stars"]:
        if mag <= limit:
            p = xy(ra, dec)
            if p:
                star_dot(layer, d, p[0], p[1], mag, star_fill or star_level(mag))
    return layer


def draw_stars(img, t, limit):
    # In half magnitudes, so twilight deepening doesn't redraw the field every minute
    limit = round(limit * 2) / 2
    layer = kept("stars", t, (limit, DOME_X, DOME_Y, DOME_R, base.HEADING), 600,
                 lambda: star_layer(t, limit, None))
    box = (DOME_X - DOME_R, DOME_Y - DOME_R, DOME_X + DOME_R + 1, DOME_Y + DOME_R + 1)
    img.paste(ImageChops.lighter(img.crop(box), layer), box[:2])


# Each named star's magnitude, so a name never goes on a star too faint to be drawn yet
STAR_MAG = {name: min(SKY["stars"], key=lambda s, ra=ra, dec=dec: (s[0] - ra) ** 2 + (s[1] - dec) ** 2)[2]
            for ra, dec, name in SKY["names"]}


def star_names(d, t, limit):
    """The two highest named stars, and only where every other label has left room: they
    go down last."""
    up = sorted(((astro.alt_az(ra, dec, t, base.HOME_LAT, base.HOME_LON), name) for ra, dec, name in SKY["names"]
                 if STAR_MAG[name] <= round(limit * 2) / 2), reverse=True)
    placed = 0
    for (el, az), name in up:
        if el <= 0 or placed == 2:
            break
        p = dome_xy(el, az)
        w, h = base.text_w(d, name, SMALL), SMALL.size
        for lx in (p[0] + 14, p[0] - 14 - w):
            box = (lx - 6, p[1] - h * 0.7, lx + w + 6, p[1] + h * 0.7)
            if inside(lx, p[1], 20) and inside(lx + w, p[1], 20) and not any(
                    box[0] < b[2] and b[0] < box[2] and box[1] < b[3] and b[1] < box[3] for b in TAKEN + PATHS):
                glow_text(d, (lx, p[1] - h * 0.6), name, SMALL, SOFT, GROUND)
                named(name, STAR_LY.get(name, 100) * KM_PER_LY, "star")
                TAKEN.append(box)
                placed += 1
                break


NEAR_MOON = 70  # a planet this close to the Moon shares its label


def glow_text(d, xy, s, f, fill, bg):
    """halo_text() against any background, not just paper."""
    x, y = xy
    for dx in (-3, 0, 3):
        for dy in (-3, 0, 3):
            if dx or dy:
                d.text((x + dx, y + dy), s, font=f, fill=bg)
    d.text(xy, s, font=f, fill=fill)


TAKEN = []
# Where the lines run: labels keep off them, but the headline's would rather cross one than
# drift from its mark
PATHS = []
# Every mark's center, so no label goes nearer another mark than its own
MARKS = []
# Everything the dome has put a name to, as (name, km, kind): the list in the panel is its key
NAMED = []


def named(name, km, kind):
    if name not in (n for n, _, _ in NAMED):
        NAMED.append((name, km, kind))


def overlaps(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def side_label(d, x, y, off, s, f, fill, bg, dy=0, must=False):
    """Label beside its mark: the eight places around it, the side facing the dome's center
    first, then the same ring a line further out. A label far from its mark is worse than
    none, so where nothing close is clear it's dropped (False), unless it `must` show,
    the headline's, which takes the place that overlaps least."""
    w, h = base.text_w(d, s, f), f.size
    spots = []
    for o in (off, off + h):
        beside = [(x + o, y - h * 0.6 + dy), (x - o - w, y - h * 0.6 + dy)]
        if x >= DOME_X:
            beside.reverse()
        spots += beside + [(x - w / 2, y - o - h * 1.1), (x - w / 2, y + o - h * 0.1),
                           (x + o * 0.7, y - o * 0.7 - h), (x + o * 0.7, y + o * 0.7),
                           (x - o * 0.7 - w, y - o * 0.7 - h), (x - o * 0.7 - w, y + o * 0.7)]

    def box(lx, ly):
        return (lx - 4, ly - 2, lx + w + 4, ly + h * 1.2)

    def overlap(sp, boxes):
        # Not counting its own mark, whose box the nearest spots just touch
        return sum(overlaps(box(*sp), t) for t in boxes
                   if math.hypot((t[0] + t[2]) / 2 - x, (t[1] + t[3]) / 2 - y) > 8)

    def gap(b, px, py):
        return math.hypot(max(b[0] - px, 0, px - b[2]), max(b[1] - py, 0, py - b[3]))

    def own(sp):
        """Nearer its own mark than any other, so it can't be read as another's name."""
        b = box(*sp)
        mine = gap(b, x, y)
        return all(gap(b, mx, my) >= mine for mx, my in MARKS if math.hypot(mx - x, my - y) > 30)

    on = [sp for sp in spots if inside(sp[0], sp[1] + h / 2, 4) and inside(sp[0] + w, sp[1] + h / 2, 4) and own(sp)]
    spot = next((sp for sp in on if not overlap(sp, TAKEN + PATHS)), None)
    if not spot and must:
        # The headline's name crosses a line before it leaves its mark: a gap is cut in the
        # line behind it, and only in the line
        spot = next((sp for sp in on if not overlap(sp, TAKEN)), None) or \
            min(on or spots, key=lambda sp: overlap(sp, TAKEN))
        b = box(*spot)
        for t in PATHS:
            if overlaps(b, t):
                d.rectangle((max(b[0], t[0]), max(b[1], t[1]), min(b[2], t[2]), min(b[3], t[3])), fill=bg)
    if not spot:
        return False
    lx, ly = spot
    TAKEN.append(box(lx, ly))
    glow_text(d, (lx, ly), s, f, fill, bg)
    return True


def draw_balloon(img, x, y, px, ink, bg, burst=False):
    """The balloon, or once it has burst, what's left coming down under its parachute."""
    icons.paste(img, icons.glyph("parachute" if burst else "balloon", px, ink), x, y, bg)


def moon_icon(r, frac, waxing, x, y, sun_xy, night, lit_shade=255):
    """The Moon's icon in the nearest of Weather Icons' 28 phases, its lit side toward
    where the sun is on the dome (turned in 5 degree steps so the cache stays small)."""
    elong = math.degrees(math.acos(max(-1.0, min(1.0, 1 - 2 * frac))))
    phase = int(round((elong if waxing else 360 - elong) / 360 * 28)) % 28
    ang = math.degrees(math.atan2(sun_xy[1] - y, sun_xy[0] - x))
    return icons.moon(2 * r, phase, int(round(ang / 5.0)) * 5, night, lit_shade)


def dash_line(d, pts, fill, width, on, off):
    """Dashes measured along the whole path, so they stay even however it's sampled."""
    carry, drawing = on, True
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        pos = 0.0
        while pos < seg:
            step = min(carry, seg - pos)
            if drawing:
                f0, f1 = pos / seg, (pos + step) / seg
                d.line((x0 + (x1 - x0) * f0, y0 + (y1 - y0) * f0, x0 + (x1 - x0) * f1, y0 + (y1 - y0) * f1),
                       fill=fill, width=width)
            pos += step
            carry -= step
            if carry <= 0:
                drawing = not drawing
                carry = on if drawing else off


def claim_path(pts, half):
    """Mark a drawn path as taken, a box every few pixels along it, so labels go beside it."""
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) // half))
        for k in range(n + 1):
            x, y = x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n
            PATHS.append((x - half, y - half, x + half, y + half))


def ghost_moon(moon, t):
    """Where a Moon rising within 4 hours waits: just outside the rim, at the point where it
    will come up, which is where to look. None when it's up, or rises later than that."""
    if not moon.get("below") or not moon.get("rises") or moon["rises"] - t > 4 * 3600:
        return None
    a = math.radians(moon["rise_az"] - base.HEADING)
    r = DOME_R + 34
    return (min(max(DOME_X + r * math.sin(a), SKY_BOX[0] + 28), SKY_BOX[2] - 28),
            min(max(DOME_Y - r * math.cos(a), SKY_BOX[1] + 28), SKY_BOX[3] - 28))


def compass_letters(d):
    """The compass points on the horizon, as (letter, font, box): N, E, S and W, and the
    points between when the way you face isn't one of those, so the top has a name."""
    pts = [(lab, az, COMPASS) for lab, az in (("N", 0), ("E", 90), ("S", 180), ("W", 270))]
    if base.HEADING % 90:
        pts += [(lab, az, SMALL) for lab, az in (("NE", 45), ("SE", 135), ("SW", 225), ("NW", 315))]
    out = []
    for lab, az, f in pts:
        x, y = dome_xy(0, az)
        w = base.text_w(d, lab, f)
        out.append((lab, f, (x - w / 2 - 4, y - f.size * 0.6 - 2, x + w / 2 + 4, y + f.size * 0.7)))
    return out


def join_names(names):
    """Moon; Moon & Mars; Moon, Mars & Jupiter."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " & " + names[-1]


def draw_dome(img, d, sky):
    t = sky["t"]
    dome, ink = GROUND, THING
    hero = sky["hero"]
    hk = hero["kind"] if hero.get("start", 0) <= t else None
    hname = hero.get("name")

    def lit(kind):
        return HERO if kind == hk else THING

    def is_hero(th):
        return th["kind"] == hk and (th["kind"] != "station" or th["name"] == hname)
    R = DOME_R
    things = sky["things"]
    up = [th for th in things if not th.get("below") and not th.get("extra")]
    del TAKEN[:]
    del PATHS[:]
    del MARKS[:]
    del NAMED[:]
    # Solid page, sky and ground alike: only the horizon line says where the sky ends
    d.ellipse((DOME_X - R, DOME_Y - R, DOME_X + R, DOME_Y + R), outline=FRAME, width=7)

    # The way you face, as a soft cone from the middle toward the top, the way a map shows
    # it. Drawn first, so everything in the sky sits on top of it
    cone = DOME_R * 0.34
    d.pieslice((DOME_X - cone, DOME_Y - cone, DOME_X + cone, DOME_Y + cone), 242, 298, fill=FRAME - 68)

    limit = mag_limit(sky["sun_el"])
    if limit:
        draw_stars(img, t, limit)
    sun_ra, sun_dec, _ = astro.sun(t)
    sel, saz = astro.alt_az(sun_ra, sun_dec, t, base.HOME_LAT, base.HOME_LON)
    sun_xy = dome_xy(sel, saz)  # off the dome when it's down, which still points the right way

    # Marks claim their space before any line or label goes down
    moon = next((th for th in things if th["kind"] == "moon"), None)
    ghost = moon and ghost_moon(moon, t)
    marks = [(ghost[0] - 30, ghost[1] - 30, ghost[0] + 30, ghost[1] + 30)] if ghost else []
    for th in up:
        x, y = dome_xy(th["el"], th["az"])
        if th["kind"] in ("balloon", "pico"):
            x, y = dome_xy(max(th["el"], 5), th["az"])
            marks.append((x - 30, y - 32, x + 30, y + 32))
            continue
        r = {"moon": 36, "station": 40, "sun": 36, "train": 18, "planet": 18}.get(th["kind"], 10)
        marks.append((x - r, y - r, x + r, y + r))
    # A meteor shower's radiant, where the streaks seem to come from, once it's dark enough
    radiant = None
    if hero.get("radiant") and sky["sun_el"] < -6:
        el, az = astro.alt_az(hero["radiant"][0], hero["radiant"][1], t, base.HOME_LAT, base.HOME_LON)
        if el > 0:
            radiant = dome_xy(el, az)
            marks.append((radiant[0] - 30, radiant[1] - 30, radiant[0] + 30, radiant[1] + 30))
    MARKS.extend(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in marks)
    # You: no label covers the dot, though one may sit nearer it than its own mark (nobody
    # reads a name as yours)
    marks.append((DOME_X - 19, DOME_Y - 19, DOME_X + 19, DOME_Y + 19))
    TAKEN.extend(marks)
    if limit:
        # The few brightest are sparkles, big enough that a label on one hides it
        for ra, dec, mag in SKY["stars"]:
            if mag < 0.6:
                el, az = astro.alt_az(ra, dec, t, base.HOME_LAT, base.HOME_LON)
                if el > 0:
                    x, y = dome_xy(el, az)
                    TAKEN.append((x - 14, y - 14, x + 14, y + 14))

    # By day, the Sun's whole path today, with a bead each hour
    day = sky.get("day")
    if day and sky["sun_el"] > SUN_HORIZON:
        pts = [dome_xy(SUN_HORIZON, day["rise_az"])] + [dome_xy(el, az) for _, el, az in day["arc"]] + \
            [dome_xy(SUN_HORIZON, day["set_az"])]
        d.line(pts, fill=FRAME, width=6, joint="curve")
        claim_path(pts, 8)
        for tt, el, az in day["arc"]:
            if time.localtime(tt).tm_min == 0:
                bx, by = dome_xy(el, az)
                d.ellipse((bx - 7, by - 7, bx + 7, by + 7), fill=SOFT)

    # Paths, so no label ends up under a line: they claim their room like the marks. The
    # headline's path is heavy, any other thin and dim, and each is named where it starts
    # unless its mark is up and named already
    labels = []
    tr = sky.get("train")
    if tr:
        path = [dome_xy(k[1], k[2]) for k in tr["track"]]
        if hero["kind"] == "train":
            dash_line(d, path, lit("train"), width=9, on=14, off=10)
        else:
            dash_line(d, path, SOFT, width=5, on=12, off=12)
        claim_path(path, 10)
        if not any(th["kind"] == "train" for th in up):
            labels.append((hero["kind"] == "train", path[0][0], path[0][1], 24, "Starlink", BLABEL,
                           lit("train") if hero["kind"] == "train" else SOFT, 0, []))
    # The headline's pass if it's a station's, else the ISS's, once it's within the hour
    ps = hero.get("pass_") or sky.get("pass")
    lead = hname if hero.get("pass_") else "ISS"
    if ps and ps["rise"] <= t + 3600 and len(ps["track"]) > 1:
        main = hero["kind"] == "station" and lead == hname
        fill = (HERO if hk == "station" else THING) if main else SOFT
        pts = [(k[0], dome_xy(k[1], k[2])) for k in ps["track"]]
        # Heavy enough to survive e-ink: flown part solid, the rest in long dashes
        flown = [p for tt, p in pts if tt <= t]
        ahead = [p for tt, p in pts if tt > t]
        if flown and ahead:
            ahead.insert(0, flown[-1])
        if len(flown) > 1:
            d.line(flown, fill=fill, width=14 if main else 6, joint="curve")
        dash_line(d, ahead, fill, width=12 if main else 5, on=26 if main else 14, off=14 if main else 12)
        claim_path([p for _, p in pts], 14)
        # Arrowhead where it leaves
        (xa, ya), (xb, yb) = pts[-2][1], pts[-1][1]
        ang = math.atan2(yb - ya, xb - xa)
        size = 1.0 if main else 0.6
        d.polygon([(xb + 42 * size * math.cos(ang), yb + 42 * size * math.sin(ang)),
                   (xb + 32 * size * math.cos(ang + 2.4), yb + 32 * size * math.sin(ang + 2.4)),
                   (xb + 32 * size * math.cos(ang - 2.4), yb + 32 * size * math.sin(ang - 2.4))], fill=fill)
        if not any(th["kind"] == "station" and th["name"] == lead for th in up):
            x, y = pts[0][1]
            labels.append((main, x, y, 26, lead, BLABEL, fill, 0, []))

    # Compass letters on the horizon, in a gap cut in the line (and in any path running
    # through it), like a compass bezel. A mark sitting on one hides it: the Moon rising
    # in the east says east better than the E it covers
    for lab, f, box in compass_letters(d):
        if any(overlaps(box, m) for m in marks):
            continue
        d.rectangle((box[0] - 4, box[1], box[2] + 4, box[3]), fill=GROUND)
        d.text((box[0] + 4, box[1] + 2), lab, font=f, fill=SOFT)
        TAKEN.append(box)

    # You, under the middle of the sky, as a map marks you: a dot, on top of the cone
    d.ellipse((DOME_X - 19, DOME_Y - 19, DOME_X + 19, DOME_Y + 19), fill=GROUND)
    d.ellipse((DOME_X - 13, DOME_Y - 13, DOME_X + 13, DOME_Y + 13), fill=THING)

    if radiant:
        x, y = radiant
        fill = HERO if hk == "shower" else THING
        for k in range(8):
            a = math.radians(k * 45 + 22.5)
            d.line((x + 12 * math.cos(a), y + 12 * math.sin(a), x + 30 * math.cos(a), y + 30 * math.sin(a)),
                   fill=fill, width=5)
        labels.append((True, x, y, 36, "Meteors", BLABEL, fill, 0, []))

    # A Moon about to rise, waiting at the rim where it will come up, with when
    if ghost:
        x, y = ghost
        icons.paste(img, moon_icon(26, moon["frac"], moon["waxing"], x, y, sun_xy, True, FRAME), x, y, dome)
        # The rise time, unless the headline is this very rise and already says it
        said = hero["kind"] == "moon" and hero.get("start") == moon["rises"]
        lab = "Moon" if said else "Moon rises " + clock_ap(moon["rises"])
        w, h = base.text_w(d, lab, SMALL), SMALL.size
        # Below, above, right or left of it: the first spot clear of the compass letters,
        # and outside the dome, where the ground is
        spots = [(x - w / 2, y + 30), (x - w / 2, y - 30 - h * 1.2), (x + 36, y - h * 0.6), (x - 36 - w, y - h * 0.6)]
        spots = [(min(max(lx, SKY_BOX[0]), SKY_BOX[2] - w), min(max(ly, SKY_BOX[1]), SKY_BOX[3] - h * 1.2))
                 for lx, ly in spots]

        def cost(sp, w=w, h=h):
            b = (sp[0] - 4, sp[1] - 2, sp[0] + w + 4, sp[1] + h * 1.2)
            return sum(overlaps(b, c) for c in TAKEN + PATHS), inside((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)

        lx, ly = min(spots, key=cost)
        TAKEN.append((lx - 4, ly - 2, lx + w + 4, ly + h * 1.2))
        glow_text(d, (lx, ly), lab, SMALL, SOFT, GROUND)
        named("Moon", moon["km"], "moon")

    planets_near = []
    for th in up:
        x, y = dome_xy(th["el"], th["az"])
        if th["kind"] == "moon":
            icons.paste(img, moon_icon(34, th["frac"], th["waxing"], x, y, sun_xy, True, lit("moon")), x, y, dome)
            near = [p for p in up if p["kind"] == "planet"
                    and math.hypot(*(a - b for a, b in zip(dome_xy(p["el"], p["az"]), (x, y)))) < NEAR_MOON]
            planets_near = [p["name"] for p in near]
            labels.append((is_hero(th), x, y, 44, join_names(["Moon"] + planets_near), LABEL, lit("moon"), -30,
                           [("Moon", th["km"], "moon")] + [(p["name"], p["km"], "planet") for p in near]))
        elif th["kind"] == "planet":
            # Ringed for the giants, a sparkle for Venus, a plain dot for Mars
            icon = {"Venus": ("sparkle", 34), "Mars": ("dot", 16)}.get(th["name"], ("planet", 38))
            icons.paste(img, icons.glyph(icon[0], icon[1], ink), x, y, dome)
        elif th["kind"] == "sun":
            icons.paste(img, icons.glyph("sun", 68, ink), x, y, dome)
            labels.append((is_hero(th), x, y, 46, "Sun", LABEL, ink, 0, [("Sun", th["km"], "sun")]))
    for th in up:
        if th["kind"] == "planet" and th["name"] not in planets_near:
            x, y = dome_xy(th["el"], th["az"])
            labels.append((False, x, y, 24, th["name"], LABEL, ink, 4, [(th["name"], th["km"], "planet")]))

    if tr:
        # A bead for each one up right now, on the path drawn with the others above
        beads = [(dome_xy(th["el"], th["az"]), th["km"]) for th in up if th["kind"] == "train"]
        for (x, y), _ in beads:
            icons.paste(img, icons.glyph("satellite", 30, lit("train")), x, y, dome)
        if beads:
            at = min(beads, key=lambda b: b[0][1])[0]
            labels.append((hk == "train", at[0], at[1], 26, "Starlink", BLABEL, lit("train"), 0,
                           [("Starlink", min(km for _, km in beads), "train")]))

    for th in up:
        if th["kind"] in ("pico", "balloon"):
            x, y = dome_xy(max(th["el"], 5), th["az"])  # nudged up off the horizon line so it all shows
            if th["kind"] == "pico":
                draw_balloon(img, x, y, 48, lit("pico"), dome)
                labels.append((is_hero(th), x, y, 32, "Balloon", BLABEL, lit("pico"), 0, [(th["name"], th["km"], "pico")]))
            else:
                draw_balloon(img, x, y, 56, lit("balloon"), dome, burst=not th["rising"])
                labels.append((is_hero(th), x, y, 36, "Balloon", BLABEL, lit("balloon"), 0, [("Balloon", th["km"], "balloon")]))
        elif th["kind"] == "station":
            x, y = dome_xy(th["el"], th["az"])
            level = lit("station") if th["name"] == hname else THING
            icon = icons.glyph("satellite", 70, level)
            icons.paste(img, icon, x, y, dome)
            labels.append((is_hero(th), x, y - 4, icon[0].width // 2 + 10, th["name"], BLABEL, level, 0,
                           [(th["name"], th["km"], "station")]))

    # The headline's label first, so it gets the clearest place; the rest only where there's room
    for must, x, y, off, s, f, fill, dy, names in sorted(labels, key=lambda lb: not lb[0]):
        if side_label(d, x, y, off, s, f, fill, dome, dy=dy, must=must):
            for name in names:
                named(*name)

    # Extras last, and whole or not at all: a mark with its name, clear of everything else
    for th in things:
        if th.get("extra") and not th.get("below"):
            x, y = dome_xy(th["el"], th["az"])
            mark = (x - 20, y - 20, x + 20, y + 20)
            if not any(overlaps(mark, b) for b in TAKEN + PATHS) and \
                    side_label(d, x, y, 24, th["name"], LABEL, ink, dome, dy=4):
                icons.paste(img, icons.glyph("sparkle", 34, ink), x, y, dome)
                named(th["name"], th["km"], "planet")

    if limit:
        star_names(d, t, limit)



# ---------- panel ----------

def fmt_km(km):
    if km >= KM_PER_LY * 0.5:
        return "%d light-years" % round(km / KM_PER_LY)
    if km >= 1e9:
        return "%.1f billion km" % (km / 1e9)
    if km >= 1e6:
        return "%d million km" % round(km / 1e6)
    return "{:,} km".format(int(round(km, -3 if km > 1e5 else 0)))


def clock(t):
    return time.strftime("%-I:%M", time.localtime(t))


def hm(seconds):
    """A duration: 11h 46m, never 11:46, which reads as a time."""
    return "%dh %02dm" % divmod(int(round(seconds / 60.0)), 60)


def ms(seconds):
    return "%dm %02ds" % divmod(int(round(seconds)), 60) if seconds >= 60 else "%ds" % round(seconds)


def moon_phase(frac, waxing):
    """In everyday words: no waxing, waning, gibbous or quarter."""
    if frac > 0.97:
        return "Full moon"
    if frac < 0.03:
        return "New moon"
    if 0.42 < frac < 0.58:
        return "Half moon"
    if frac < 0.42:
        return "Crescent moon"
    return "Moon, nearly full" if waxing else "Moon, past full"


def clock_ap(t):
    """A time with am or pm, for where nothing beside it says which half of the day."""
    return clock(t) + (" am" if time.localtime(t).tm_hour < 12 else " pm")


def days_apart(t, now):
    """Calendar days from now's date to t's, counted noon to noon, so a change of clocks or
    the new year can't throw it."""
    a, b = time.localtime(t), time.localtime(now)
    return int(round((time.mktime(a[:3] + (12, 0, 0, 0, 0, -1)) - time.mktime(b[:3] + (12, 0, 0, 0, 0, -1))) / 86400))


def when_clock(t, now):
    """8:01 pm, or 'tomorrow 8:01 am' / 'Sat 8:01 am' on another day."""
    days = days_apart(t, now)
    return clock_ap(t) if days == 0 else ("tomorrow " if days == 1 else time.strftime("%a ", time.localtime(t))) + clock_ap(t)


def day_word(t, now):
    """When, as words that also say am or pm: THIS MORNING, THIS AFTERNOON, TONIGHT, LATE
    TONIGHT, TOMORROW NIGHT, SAT MORNING. A night runs to 6 am, so 2:00 after Saturday is
    Saturday night, and after midnight the coming evening is THIS EVENING, not tonight."""
    lt = time.localtime(t)
    if 6 <= lt.tm_hour < 18:
        days = days_apart(t, now)
        part = "MORNING" if lt.tm_hour < 12 else "AFTERNOON"
        return ("THIS " if days <= 0 else "TOMORROW " if days == 1 else time.strftime("%a ", lt).upper()) + part
    night = t - 6 * 3600
    days = days_apart(night, now)
    if days <= 0:
        if lt.tm_hour >= 18 and time.localtime(now).tm_hour < 6:
            return "THIS EVENING"
        return "LATE TONIGHT" if lt.tm_hour < 6 else "TONIGHT"
    if days == 1:
        return "TOMORROW NIGHT"
    return time.strftime("%a", time.localtime(night)).upper() + " NIGHT"


def look_when(start, end, t, az):
    """The line under the path, as what to do: where to look and when once it's close, how
    long it lasts while it's further off, and that it's up once it is."""
    if t >= start:
        return "Up now" if t <= end else "Gone"
    if start - t < 90 * 60:
        return "Look %s at %s" % (base.compass(az), clock(start))
    return "Lasts %d min" % max(1, round((end - start) / 60))


def height(el, az=None):
    """How high, in words that match the dome: the rim is LOW, the middle OVERHEAD."""
    word = "LOW" if el < 20 else "HALFWAY\u00a0UP" if el < 50 else "HIGH" if el < 75 else "OVERHEAD"
    # No-break spaces, so a narrow column breaks it as LOW / IN THE SE
    return word if az is None or word == "OVERHEAD" else "%s IN\u00a0THE\u00a0%s" % (word, base.compass(az))


def along(start, end, t):
    return min(1.0, max(0.0, (t - start) / float(max(1, end - start))))


# The frame invites; it never complains. Every line is something to look forward to or go
# out for: a shortening day is told as the hour the stars come out, and a shower washed out
# by the Moon steps back rather than saying so.
#
# What's worth looking up for, and when. Every candidate is an event with a window and a
# wonder from 1 (a sunset) to 5 (an eclipse). The headline is the event scoring highest
# right now: a thing that's on scores its wonder in full; a thing still to come scores
# less the further off it is, with a lead that grows with wonder, so a sunset only matters
# in the moment while a great ISS pass takes the afternoon and a big meteor shower the day
# before. Below the headline, "Next" names the best thing in the coming two days, and "Up
# ahead" the best thing in the two months after: short and long term, so there's always
# something tonight and something to look forward to. Plain words throughout: "Jupiter at
# its brightest", never "opposition".
LEAD_H = {1: 0.5, 2: 2, 3: 6, 4: 24, 5: 24 * 7}
# The major showers' peak nights, from the International Meteor Organization: the rate an
# hour under a perfectly dark sky with the radiant overhead (ZHR), the population index r
# (how fast the count falls as the sky brightens) and the radiant, RA and Dec
SHOWERS = (("Quadrantids", 1, 3, 80, 2.1, 230, 49), ("Lyrids", 4, 22, 18, 2.1, 271, 34),
           ("Eta Aquariids", 5, 5, 50, 2.4, 338, -1), ("Perseids", 8, 12, 100, 2.2, 48, 58),
           ("Orionids", 10, 21, 20, 2.5, 95, 16), ("Leonids", 11, 17, 15, 2.5, 152, 22),
           ("Geminids", 12, 13, 150, 2.6, 112, 33))
# Config "sky_glow": how faint a star you can see overhead (limiting magnitude). There's
# no telling a city from a field on the device, so it's set; a city sky by default
SKY_GLOW = {"dark": 6.5, "rural": 6.0, "suburb": 5.5, "city": 4.5, "downtown": 4.0}
CLOUDY = 70  # percent cloud over a shower night that hides it


def score(ev, t):
    if t > ev["end"]:
        return 0.0
    if t >= ev["start"]:
        return float(ev["wonder"])
    lead = LEAD_H[ev["wonder"]]
    return ev["wonder"] * lead / (lead + (ev["start"] - t) / 3600.0)


def how_soon(at, now, timed):
    """For the Next line: 8:49 tonight, tomorrow night, in 25 days."""
    days = days_apart(at - (6 * 3600 if time.localtime(at).tm_hour < 6 else 0), now)
    # No-break spaces: when the line wraps, it breaks between the what and the when
    if days >= 2:
        return "in\u00a0%d\u00a0days" % days
    return ((clock(at) + " " if timed else "") + day_word(at, now).lower()).replace(" ", "\u00a0")


def in_days(at, now):
    """For Up ahead: in 5 days, or in 6 weeks once it's three weeks off, so it doesn't
    tick over every day."""
    days = days_apart(at - (6 * 3600 if time.localtime(at).tm_hour < 6 else 0), now)
    return ("in\u00a0%d\u00a0days" % days) if days < 21 else "in\u00a0%d\u00a0weeks" % round(days / 7.0)


def night_word(t, now):
    """Tonight, tomorrow night, Sat night, or the date past a week: for things that belong to a night."""
    if t - now > 6 * 86400:
        return time.strftime("%b %-d", time.localtime(t))
    return day_word(t, now).lower()


def pass_event(name, ps, t):
    """A visible pass of a space station. Tiangong only counts from 30° up: lower, it's a
    faint dot in the haze, and the ISS already teaches the eye what a pass looks like."""
    up = "overhead" if ps["peak_el"] >= 60 else "pass"
    if name == "ISS":
        wonder = 4 if ps["peak_el"] >= 60 else (3 if ps["peak_el"] >= 25 else 2)
    elif ps["peak_el"] >= 30:
        wonder = 3 if ps["peak_el"] >= 60 else 2
    else:
        return None
    return dict(kind="station", name=name, pass_=ps, wonder=wonder,
                start=ps["rise"], end=ps["set"], head=name + " " + up,
                stats=[when_stat(ps["peak"], ps["rise"], ps["set"], t), ("%d°" % ps["peak_el"], height(ps["peak_el"]))],
                path=path(ps["rise_az"], ps["set_az"], along(ps["rise"], ps["set"], t)),
                foot=look_when(ps["rise"], ps["set"], t, ps["rise_az"]),
                next=(name + (" overhead" if up == "overhead" else ""), ps["peak"], True))


def when_stat(at, start, end, t):
    """The time to go out, with when as words; once it's on, when it'll be gone instead."""
    return (clock(end), "GONE BY") if t >= start else (clock(at), day_word(at, t))


def path(rise_az, set_az, frac):
    return (base.compass(rise_az), base.compass(set_az), frac, rise_az, set_az)


def shower_events(t, lat, lon, limit):
    """This year's and next year's peak nights, 10 pm to 5 am, with what you'd really see
    from here: the IMO's rate, ZHR x sin(radiant height) x r^(limit - 6.5), at the best
    hour, the limit lowered by the Moon while it's up. Under 5 an hour isn't worth going out
    for and isn't shown; under 10 only on the Next line."""
    out = []
    year = time.localtime(t).tm_year
    for name, m, d, zhr, r, ra, dec in SHOWERS:
        for y in (year, year + 1):
            start = time.mktime((y, m, d, 22, 0, 0, 0, 0, -1))
            best = (0, start)
            for tt in range(int(start), int(start) + 7 * 3600 + 1, 1800):
                h = astro.alt_az(ra, dec, tt, lat, lon)[0]
                if h <= 0 or astro.sun_alt(tt, lat, lon) > -12:
                    continue  # radiant down, or dawn already washing the sky out
                ma, _, _, frac, _ = astro.moon_alt_az(tt, lat, lon)
                seen = limit - (0.8 * frac if ma > 0 else 0)
                best = max(best, (zhr * math.sin(math.radians(h)) * r ** (seen - 6.5), tt))
            rate, at = best
            if rate < 5:
                continue
            out.append(dict(kind="shower", wonder=4 if rate >= 20 else 3 if rate >= 10 else 2, next_only=rate < 10,
                            start=start, end=start + 7 * 3600, head=name[:-1] + " meteors", best=at, radiant=(ra, dec),
                            rate="%d" % (rate if rate < 10 else 5 * round(rate / 5.0)),
                            next=(name[:-1] + " meteors", start, False), yearly=True))
    return out


def shower_list(t):
    lat, lon = base.HOME_LAT, base.HOME_LON
    limit = SKY_GLOW.get((base.LAST_CFG or {}).get("sky_glow"), SKY_GLOW["city"])
    return kept("showers", t, (time.localtime(t).tm_year, limit, lat, lon), 86400,
                lambda: shower_events(t, lat, lon, limit))


def clouded(ev, clouds):
    """True when the forecast has the shower's night mostly cloudy."""
    hours = [pct for when, pct in (clouds or {}).get("hours", []) if ev["start"] <= when < ev["end"]]
    return len(hours) >= 3 and sum(hours) / len(hours) >= CLOUDY


NEXT_H = 48           # Next: the best thing in the coming two days
AHEAD_DAYS = 60       # Up ahead: the best thing after that, out to two months
# The full moons' old names, as almanacs still print them, by the month they fall in
MOON_NAMES = ("Wolf", "Snow", "Worm", "Pink", "Flower", "Strawberry", "Buck", "Sturgeon",
              "Corn", "Hunter's", "Beaver", "Cold")
FULL_MOONS = {n + " Moon" for n in MOON_NAMES + ("Harvest",)} | {"Supermoon", "Blue moon", "Full moon"}


def nearest_night(tt):
    """11 pm on the night closest to tt, so a full moon at 10 am is 'tonight's' or last
    night's, never 'this morning's'."""
    lt = time.localtime(tt)
    nights = [time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + k, 23, 0, 0, 0, 0, -1)) for k in (-1, 0)]
    return min(nights, key=lambda n: abs(n - tt))


def sep(ra1, dec1, ra2, dec2):
    """Angle between two points on the sky, degrees."""
    a, b = math.radians(dec1), math.radians(dec2)
    c = math.sin(a) * math.sin(b) + math.cos(a) * math.cos(b) * math.cos(math.radians(ra1 - ra2))
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def full_moons(t, days):
    """Every full moon from t, to the minute: where the Moon's longitude is opposite the Sun's."""
    def gap(tt):
        return (astro.moon_ecliptic(tt)[0] - astro.sun(tt)[2] - 180 + 540) % 360 - 180
    out, tt = [], t
    while tt < t + days * 86400:
        a, b = gap(tt), gap(tt + 6 * 3600)
        if a < 0 <= b:
            lo, hi = tt, tt + 6 * 3600
            while hi - lo > 60:
                mid = (lo + hi) / 2
                lo, hi = (mid, hi) if gap(mid) < 0 else (lo, mid)
            out.append(lo)
        tt += 6 * 3600
    return out


def daily(t, days, f):
    """f at noon on each day from two days before t to `days` after: [(noon, value)]."""
    lt = time.localtime(t)
    noons = [time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + k, 12, 0, 0, 0, 0, -1)) for k in range(-2, days + 1)]
    return [(n, f(n)) for n in noons]


def peaks(series, bigger=True):
    """The days a value is at its highest (or lowest) of the days around it."""
    sign = 1 if bigger else -1
    return [(n, v) for (_, a), (n, v), (_, b) in zip(series, series[1:], series[2:])
            if sign * v > sign * a and sign * v >= sign * b]


def ahead_events(t, lat, lon):
    """What's coming in the next two months, worked out once a day: the full moons by
    their names (and the special ones), eclipses of the Moon you can see from here,
    planets at their brightest, the Moon passing close to Venus or Jupiter, and the turns
    of the seasons. Each is (wonder, at, label, night); night means its words are about a
    night ("tomorrow night"), else a day."""
    out = []
    moons = full_moons(t - 32 * 86400, AHEAD_DAYS + 32)

    def harvest(fm):
        # The full moon nearest the September equinox; the one after it is the Hunter's
        equinox = time.mktime((time.localtime(fm).tm_year, 9, 22, 12, 0, 0, 0, 0, -1))
        return abs(fm - equinox) < 15 * 86400 and all(abs(m - equinox) >= abs(fm - equinox) for m in moons)
    for i, fm in enumerate(moons):
        if fm < t:
            continue
        lam, beta, dist = astro.moon_ecliptic(fm)
        ma = astro.moon_alt_az(fm, lat, lon)[0]
        lt = time.localtime(fm)
        # The Moon misses Earth's shadow unless it passes within about a degree of the Sun's
        # path. Checked against NASA's eclipses 2026-30: every one deeper than a sliver
        # passes under 0.85° here and every near miss over it. The formula can't tell total
        # from deep partial, so it never says total; the deep ones just rank higher
        if abs(beta) < 0.85 and ma > 0 and astro.sun_alt(fm, lat, lon) < -6:
            out.append((5 if abs(beta) < 0.5 else 4, fm, "Eclipse of the Moon", True))
        elif dist < 361000:
            out.append((3, nearest_night(fm), "Supermoon", True))
        elif i and time.localtime(moons[i - 1]).tm_mon == lt.tm_mon:
            out.append((3, nearest_night(fm), "Blue moon", True))
        elif lat > 0:
            name = "Harvest" if harvest(fm) else "Hunter's" if i and harvest(moons[i - 1]) else                 MOON_NAMES[lt.tm_mon - 1]
            out.append((2, nearest_night(fm), name + " Moon", True))
        else:
            out.append((2, nearest_night(fm), "Full moon", True))
    # Planets at their brightest: opposite the Sun, up all night
    sun_at = {}

    def from_sun(name):
        def f(n):
            if n not in sun_at:
                sun_at[n] = astro.sun(n)[:2]
            ra, dec, _ = astro.planet(name, n)
            return sep(ra, dec, *sun_at[n])
        return f
    for name in ("Mars", "Jupiter", "Saturn"):
        for n, v in peaks(daily(t, AHEAD_DAYS, from_sun(name))):
            if v > 170:
                out.append((3, nearest_night(n), name + " at its brightest", True))
    # Venus at its furthest from the Sun: highest in the sky after sunset, or before sunrise
    for n, v in peaks(daily(t, AHEAD_DAYS, from_sun("Venus"))):
        if v > 40:
            ra = astro.planet("Venus", n)[0]
            evening = (ra - astro.sun(n)[0]) % 360 < 180
            out.append((3, n, "Venus highest " + ("after sunset" if evening else "before sunrise"), False))
    out += moon_meetings(t, lat, lon)
    # The turns of the year, said as what's good about them
    if abs(lat) > 10:
        north = lat > 0
        dec = daily(t, AHEAD_DAYS, lambda n: astro.sun(n)[1])
        for n, _ in peaks(dec):
            out.append((2, n, "Longest day of the year" if north else "Days start getting longer", False))
        for n, _ in peaks(dec, bigger=False):
            out.append((2, n, "Days start getting longer" if north else "Longest day of the year", False))
        for (_, a), (n, b) in zip(dec, dec[1:]):
            if a < 0 <= b:
                out.append((2, n, "First day of spring" if north else "First day of fall", False))
            elif a >= 0 > b:
                out.append((2, n, "First day of fall" if north else "First day of spring", False))
    return [ev for ev in out if ev[1] >= t]


def moon_meetings(t, lat, lon):
    """Nights the Moon passes within 3° of Venus or Jupiter, both up in a dark sky: an easy,
    lovely sight. The closest night of each meeting, measured as you'd see it."""
    lt = time.localtime(t)
    found = {"Venus": [], "Jupiter": []}
    for k in range(AHEAD_DAYS + 1):
        night = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + k, 17, 0, 0, 0, 0, -1))
        # The planets hardly move against the stars in a night: once a night will do
        where = {name: astro.planet(name, night + 7 * 3600)[:2] for name in found}
        best = {}
        for h in range(15):
            tt = night + h * 3600
            if astro.sun_alt(tt, lat, lon) > -8:
                continue
            m_el, m_az = astro.moon_alt_az(tt, lat, lon)[:2]
            if m_el < 10:
                continue
            for name in found:
                el, az = astro.alt_az(*where[name], tt, lat, lon)
                if el < 10:
                    continue
                d = sep(m_az, m_el, az, el)
                if d < best.get(name, (99,))[0]:
                    best[name] = (d, tt)
        for name, (d, tt) in best.items():
            found[name].append((d, tt))
    out = []
    for name, nights in found.items():
        for i, (d, tt) in enumerate(nights):
            closest = all(d <= other[0] for other in nights[max(0, i - 2):i + 3])
            if d < 3 and closest:
                out.append((3, tt, "Moon close to " + name, True))
    return out


def ahead_list(t):
    lat, lon = base.HOME_LAT, base.HOME_LON
    return kept("ahead", t, (time.strftime("%Y-%m-%d", time.localtime(t)), lat, lon), 86400,
                lambda: ahead_events(t, lat, lon))


def events(sky):
    """Every candidate headline, with its window and wonder, set out the same way each
    time: a headline, two big numbers, a path from where it rises to where it
    sets with the thing on it, and a line under that."""
    t, things, tr = sky["t"], sky["things"], sky.get("train")
    lat, lon = base.HOME_LAT, base.HOME_LON
    evs = []
    if tr:
        evs.append(dict(kind="train", wonder=4, start=tr["start"], end=tr["end"], head="Starlink train",
                        stats=[("%d" % tr["n"], "SATELLITES"), when_stat(tr["start"], tr["start"], tr["end"], t)],
                        path=path(tr["rise_az"], tr["set_az"], along(tr["start"], tr["end"], t)),
                        foot=look_when(tr["start"], tr["end"], t, tr["rise_az"]), next=("Starlink train", tr["start"], True)))
    for name, station_pass in sky.get("passes", []):
        ev = pass_event(name, station_pass, t)
        if ev:
            evs.append(ev)
    pico = next((th for th in things if th["kind"] == "pico"), None)
    if pico:
        # A balloon on its own, from a ham radio club or a school: the long ones circle the world
        evs.append(dict(kind="pico", wonder=4 if (pico["days"] or 0) >= 7 else 3, start=t, end=t, head=pico["name"],
                        stats=[("%.0f" % pico["alt_km"], "KM HIGH"), ("%d°" % pico["el"], height(pico["el"], pico["az"]))],
                        foot="Day %d aloft" % pico["days"] if pico["days"] else
                        "Launched today" if pico["days"] == 0 else None))
    b = next((th for th in things if th["kind"] == "balloon"), None)
    if b:
        evs.append(dict(kind="balloon", wonder=3, start=t, end=t, head="Weather balloon",
                        stats=[("%.0f" % b["alt_km"], "KM HIGH"), ("%d°" % b["el"], height(b["el"], b["az"]))],
                        foot=("Climbing" if b["rising"] else "Falling") + launch_site(b["track"][0])))
    day = sky.get("day")
    sun = next((th for th in things if th["kind"] == "sun"), None)
    if day:
        # Daylight: the day as a path from sunrise to sunset, and how it's changing
        yd, tm = sky.get("yesterday"), sky.get("tomorrow")
        diff = day["length"] - yd["length"] if yd else 0
        span = year_span(sky)
        longest = yd and tm and day["length"] >= max(yd["length"], tm["length"]) and span > 1
        evs.append(dict(kind="sun", wonder=2, start=day["rise"], end=day["set"], head="Sunset " + clock(day["set"]),
                        stats=[(hm(day["length"]), "OF DAYLIGHT"),
                               ("%d°" % max(0, sun["el"] if sun else 0), height(sun["el"] if sun else 0, sun["az"] if sun else 180))],
                        path=path(day["rise_az"], day["set_az"], along(day["rise"], day["set"], t)),
                        icon="sun",
                        foot="Longest day of the year" if longest else
                        ("Gaining %s a day" % ms(diff) if diff > 0 and span > 1 else
                         ("Stars out by " + clock_ap(day["dark"]) if day.get("dark") else None))))
    else:
        # The Sun stays up all day, or down: the far north's summer and winter
        up = day_length_h(t, lat) > 12
        turn = kept("polar", t, time.strftime("%Y-%m-%d", time.localtime(t)), 86400,
                    lambda: next((k for k in range(1, 200) if 0 < day_length_h(t + k * 86400, lat) < 24), None))
        evs.append(dict(kind="sun", wonder=3, start=t, end=t + 3600, head="Midnight sun" if up else "Polar night",
                        stats=[("24h", "OF DAYLIGHT"), ("%d°" % sun["el"], height(sun["el"], sun["az"]))]
                        if up and sun and sun["el"] > 0 else [],
                        foot=("Sunset" if up else "Sunrise") + (" in %d days" % turn if turn and turn > 1 else
                                                               " tomorrow" if turn else " in months")))
    rise = day["rise"] if day and t < day["rise"] else (sky.get("tomorrow") or {}).get("rise")
    if rise:
        evs.append(dict(kind="sun", wonder=1, start=rise, end=rise + 3600, head="Sunrise " + clock(rise), stats=[]))
    moon = next((th for th in things if th["kind"] == "moon"), None)
    if moon:
        full = moon["frac"] > 0.97
        phase = moon_phase(moon["frac"], moon["waxing"])
        if full:
            # Tonight's full moon by its name, when it has one (the Hunter's Moon, a supermoon)
            phase = next((label for _, at, label, _ in ahead_list(t)
                          if label in FULL_MOONS and abs(at - t) < 36 * 3600), phase)
        if not moon.get("below") and sky["sun_el"] < 0:
            # A full or new moon says how lit it is in its name; the percent is for the others.
            # Low in the haze of the horizon it's a sight for whoever happens to look
            lit = [] if full or phase == "New moon" else [("%d%%" % round(moon["frac"] * 100), "LIT")]
            evs.append(dict(kind="moon", wonder=1 if moon["el"] < 10 else (3 if full else 2), start=t,
                            end=moon.get("sets") or t + 3600, head=phase,
                            stats=[("%d°" % moon["el"], height(moon["el"], moon["az"]))] + lit,
                            foot="Sets %s" % when_clock(moon["sets"], t) if moon.get("sets") else None))
        elif moon.get("rises") and astro.sun_alt(moon["rises"], lat, lon) < 0:
            # Rising later tonight: a headline in advance, once it's the best thing coming
            evs.append(dict(kind="moon", wonder=3 if full else 2, start=moon["rises"], end=moon["rises"] + 6 * 3600,
                            head=phase, stats=[(clock(moon["rises"]), day_word(moon["rises"], t)),
                                               ("%d%%" % round(moon["frac"] * 100), "LIT")],
                            foot="Rises in the " + base.compass(moon["rise_az"]),
                            # The dome already says it when the Moon waits at the rim
                            next=None if ghost_moon(moon, t) else ("Moon rises", moon["rises"], True)))
    # Kept for the day; the words for when are worked out now, so they're never a day stale.
    # A night the forecast has under cloud just isn't mentioned
    for ev in shower_list(t):
        if clouded(ev, sky.get("clouds")):
            continue
        # Where the streaks come from: now, while it's up in the dark, else at the best hour
        el, az = astro.alt_az(ev["radiant"][0], ev["radiant"][1], t, lat, lon)
        if el <= 0 or sky["sun_el"] > -6:
            el, az = astro.alt_az(ev["radiant"][0], ev["radiant"][1], ev["best"], lat, lon)
        evs.append(dict(ev, stats=[(ev["rate"], "AN\u00a0HOUR FROM\u00a0HERE"),
                                   (clock(ev["best"]), day_word(ev["best"], t)) if t < ev["best"] else
                                   (clock(ev["end"]), "GONE BY")],
                        foot="Streaking from overhead" if el >= 75 else "Streaking out of the " + base.compass(az)))
    return evs


def hero(sky):
    """The headline and, below it, Next and Up ahead."""
    t = sky["t"]
    evs = events(sky)
    # Ties: what you can see over what you can't (a balloon is a dot at best), the station
    # over a train, then the sooner
    rank = {"station": 3, "train": 2, "shower": 2, "moon": 1, "sun": 1}
    heads = [ev for ev in evs if not ev.get("next_only")]
    best = max(heads, key=lambda ev: (score(ev, t), rank.get(ev["kind"], 0), -ev["start"])) if heads else None
    # A copy: the events are kept between frames, and this one's Next is only for now
    best = dict(best) if best and score(best, t) > 0 else dict(kind=None, head="Clear above", stats=[])
    # What's coming, as (wonder, when, words, timed, long term, a night's): the headline's
    # own events, and the almanac's (a day's, like a solstice, only ever Up ahead)
    coming = [(ev["wonder"], ev["next"][1], ev["next"][0], ev["next"][2], bool(ev.get("yearly")), True)
              for ev in evs if ev.get("next") and t < ev["start"]
              and not (ev["kind"] == best["kind"] and ev["start"] == best["start"])]
    coming += [(w, at, label, False, True, night) for w, at, label, night in ahead_list(t)
               if label != best["head"]]
    soon = [c for c in coming if c[1] < t + NEXT_H * 3600 and c[5]]
    nxt = min(soon, key=lambda c: (-c[0], c[1])) if soon else None
    later = [c for c in coming if c[4] and t + NEXT_H * 3600 <= c[1] < t + AHEAD_DAYS * 86400
             and not (nxt and c[2] == nxt[2])]
    up = min(later, key=lambda c: (-c[0], c[1])) if later else None
    best["next"] = (nxt[2], how_soon(nxt[1], t, nxt[3])) if nxt else None
    best["ahead"] = (up[2], in_days(up[1], t)) if up else None
    return best


def launch_site(fix):
    """", from Buffalo": where the balloon went up, by name for the sites people know, else
    by distance. Nothing when it was first heard already high: that's not where it started."""
    if fix[3] > 3000:
        return ""
    for name, lat, lon in SONDE_SITES:
        if base.distance_bearing(lat, lon, fix[1], fix[2])[0] < 40:
            return ", from " + name
    dist, brg = base.distance_bearing(base.HOME_LAT, base.HOME_LON, fix[1], fix[2])
    return ", from %d km %s" % (round(dist, -1), base.compass(brg))


SONDE_SITES = (("Buffalo", 42.94, -78.72), ("Detroit", 42.70, -83.47), ("Albany", 42.69, -73.83),
               ("Maniwaki", 46.30, -76.01), ("Pittsburgh", 40.53, -80.22))


# Distances of the named stars, light-years, for the list in the panel
STAR_LY = {"Vega": 25, "Deneb": 2600, "Altair": 17, "Arcturus": 37, "Capella": 43, "Aldebaran": 65,
           "Polaris": 430, "Betelgeuse": 550, "Rigel": 860, "Sirius": 8.6, "Procyon": 11.5,
           "Pollux": 34, "Castor": 51, "Regulus": 79, "Spica": 250, "Antares": 550, "Fomalhaut": 25,
           "Canopus": 310, "Achernar": 139, "Acrux": 320, "Hadar": 390, "Rigil Kentaurus": 4.4}


def wind_turn(pts):
    """Height (km) where the balloon's east-west drift reverses by more than a km, or None."""
    lo = hi = 0
    for i, (x, _alt) in enumerate(pts):
        if x < pts[lo][0]:
            lo = i
        if x > pts[hi][0]:
            hi = i
        if pts[lo][0] < x - 1 and lo:
            return pts[lo][1]
        if pts[hi][0] > x + 1 and hi:
            return pts[hi][1]
    return None


def draw_balloon_side(d, b, x0, y, width):
    """The balloon's flight side-on: height against east-west drift from the launch, so a
    change of wind with height shows as a bend. Returns the y below it."""
    y += 40  # headroom for the balloon at the top of its climb
    tr = b["track"]
    lat0, lon0 = tr[0][1], tr[0][2]
    # East on whichever side the dome has it, so the drift and the dome agree
    east = 1 if dome_xy(0, 90)[0] >= dome_xy(0, 270)[0] else -1
    pts = [(east * (lo - lon0) * 111.32 * math.cos(math.radians(lat0)), a / 1000) for _, la, lo, a in tr]
    top_km = max(35.0, pts[-1][1])
    cw, ch = width - base.text_w(d, "30 km", SMALL) - 16, 170
    turn = wind_turn(pts)
    tx_km = next(x for x, a in pts if a >= turn) if turn else None
    xs = [x for x, _ in pts]
    lo_km, hi_km = min(xs), max(xs)
    # Room for "wind turns" on the outside of the bend, where the line isn't
    room = base.text_w(d, "wind turns", SMALL) + 24
    west_bend = turn is not None and tx_km - lo_km < hi_km - tx_km
    lpad, rpad = (room, 16) if west_bend else (16, room if turn else 16)
    per_km = min((cw - lpad - rpad) / max(hi_km - lo_km, 0.1), cw / 8.0)  # small drifts stay small
    mid = (lo_km + hi_km) / 2
    cx = x0 + lpad + (cw - lpad - rpad) / 2

    def xy(x, alt):
        return cx + (x - mid) * per_km, y + ch - alt / top_km * ch

    for km in (10, 20, 30):
        gy = xy(0, km)[1]
        d.line((x0, gy, x0 + cw, gy), fill=FRAME, width=3)
        d.text((x0 + cw + 10, gy - SMALL.size * 0.6), "%d km" % km, font=SMALL, fill=SOFT)
    d.line((x0, y + ch, x0 + cw, y + ch), fill=FRAME, width=5)
    d.line([xy(x, a) for x, a in pts], fill=HERO, width=8, joint="curve")
    nx, ny = xy(*pts[-1])
    draw_balloon(base.CANVAS, nx, ny, 36, HERO, GROUND, burst=not b["rising"])
    if turn:
        tx, ty = xy(tx_km, turn)
        lab = "wind turns"
        lx = tx - 14 - base.text_w(d, lab, SMALL) if west_bend else tx + 14
        # A gap in the gridline behind it
        d.rectangle((lx - 8, ty - SMALL.size * 0.6, lx + base.text_w(d, lab, SMALL) + 8, ty + SMALL.size * 0.7), fill=GROUND)
        glow_text(d, (lx, ty - SMALL.size * 0.6), lab, SMALL, SOFT, GROUND)
    lab = "west      drift      east" if east > 0 else "east      drift      west"
    d.text((x0 + cw / 2 - base.text_w(d, lab, SMALL) / 2, y + ch + 6), lab, font=SMALL, fill=SOFT)
    return y + ch + SMALL.size + 30


def draw_stats(d, x, y, w, stats):
    """Two big numbers with their caps under them, in two fixed columns so the second number doesn't move from state to state. Both shrink
    together when one won't fit; caps wrap to a second line."""
    gap = 24
    cw = (w - gap) // 2
    sf = NUM
    while sf.size > 56 and any(base.text_w(d, v, sf) > cw for v, _ in stats):
        sf = base.font(TF["num"], sf.size - 4)
    rows = 1
    for i, (value, lab) in enumerate(stats):
        # Only a value too wide even at the smallest size (a day's length) pushes the other over
        sx = x if not i else max(x + cw + gap, x + base.text_w(d, stats[0][0], sf) + 40)
        d.text((sx, y), value, font=sf, fill=HERO)
        lines = base.wrap(d, lab, TF["name"], CAPS.size, cw, floor=CAPS.size)
        for k, (ln, f) in enumerate(lines):
            d.text((sx + 2, y + sf.size + 10 + k * (CAPS.size + 4)), ln, font=f, fill=SOFT)
        rows = max(rows, len(lines))
    return y + sf.size + rows * (CAPS.size + 4) + 40


def draw_path(d, x, y, w, rise, sets, frac, rise_az, set_az, icon):
    """Where it comes up and where it goes down, solid for the part it has crossed, with
    the thing itself on the line, like a progress bar. It runs the
    way the dome does: whichever end is further left there is on the left here."""
    ly = y + 10
    flip = dome_xy(0, rise_az)[0] > dome_xy(0, set_az)[0]
    a, b = (x + w, x) if flip else (x, x + w)  # where it rises, where it sets
    side = -1 if flip else 1
    fx = a + side * (22 + int((w - 44) * frac))
    d.line((min(fx, b), ly, max(fx, b), ly), fill=FRAME, width=8)
    d.line((min(a, fx), ly, max(a, fx), ly), fill=HERO, width=8)
    d.ellipse((min(a - side, a + side * 17), ly - 9, max(a - side, a + side * 17), ly + 9), fill=HERO)
    d.ellipse((min(b, b - side * 18), ly - 9, max(b, b - side * 18), ly + 9), outline=SOFT, width=5, fill=GROUND)
    icons.paste(base.CANVAS, icons.glyph(icon, 50, HERO, 0, 6), fx, ly, GROUND)
    left, right = (sets, rise) if flip else (rise, sets)
    d.text((x, y + 40), left, font=CAPS, fill=SOFT)
    d.text((x + w - base.text_w(d, right, CAPS), y + 40), right, font=CAPS, fill=SOFT)
    return y + 40 + CAPS.size + 30


YEAR_ROOM = 200   # the year's curve at its smallest, with its labels


def year_span(sky):
    return max(h for _, h in sky["year"]) - min(h for _, h in sky["year"])


def draw_year(d, sky, x0, y, width, bottom):
    """Hours of daylight through the year, today on it: where the year stands between the
    solstices. As a sparkline marks its extremes: the longest day's value above the peak,
    the shortest's below the trough, so the line never runs through either, months under."""
    pts = sky["year"]
    lo, hi = min(h for _, h in pts), max(h for _, h in pts)
    if hi - lo < 1:
        return  # near the equator the year hardly changes the day: a flat line says nothing
    line_h = SMALL.size + 10
    top = y + line_h
    ch = min(150, bottom - top - 2 * line_h - 10)
    if ch < 70:
        return

    def xy(doy, h):
        return x0 + (doy - 1) / 365.0 * width, top + ch - (h - lo) / (hi - lo) * ch

    d.line([xy(*p) for p in pts], fill=SOFT, width=5, joint="curve")
    today = time.localtime(sky["t"]).tm_yday
    now_h = min(hi, max(lo, day_length_h(sky["t"], base.HOME_LAT)))
    for (doy, h), above in ((max(pts, key=lambda p: p[1]), True), (min(pts, key=lambda p: p[1]), False)):
        if abs(doy - today) < 12 or abs(h - now_h) < 0.05:
            continue  # today is the extreme (or level with it, where the Sun never sets): its dot says so
        px_, py_ = xy(doy, h)
        lab = hm(h * 3600)
        lw = base.text_w(d, lab, SMALL)
        lx = min(max(px_ - lw / 2, x0), x0 + width - lw)
        d.text((lx, py_ - line_h - 2 if above else py_ + 10), lab, font=SMALL, fill=SOFT)
    for i, m in enumerate("JFMAMJJASOND"):
        mx = x0 + (i + 0.5) / 12.0 * width
        d.text((mx - base.text_w(d, m, SMALL) / 2, top + ch + line_h + 6), m, font=SMALL, fill=FRAME)
    tx, ty = xy(today, now_h)
    d.ellipse((tx - 13, ty - 13, tx + 13, ty + 13), fill=HERO)


def draw_panel(d, sky):
    x0, x1 = PANEL_X, PANEL_R
    width = x1 - x0
    y = base.TEXT[1] - 6
    h = sky["hero"]
    for ln, f in base.wrap(d, h["head"], TF["head"], px(112), width, floor=px(64)):
        d.text((x0, y), ln, font=f, fill=HERO)
        y += f.size + 4
    y += 30
    if h["stats"]:
        y = draw_stats(d, x0, y, width, h["stats"])
    if h.get("path"):
        y = draw_path(d, x0, y + 14, width, *h["path"], icon=h.get("icon", "satellite"))
    if h["kind"] == "balloon":
        b = next(th for th in sky["things"] if th["kind"] == "balloon")
        y = draw_balloon_side(d, b, x0, y - 30, width)
    if h.get("foot"):
        ff = base.fit_font(d, h["foot"], TF["head"], px(66), width)
        d.text((x0, y), h["foot"], font=ff, fill=HERO)
        y += ff.size + 20

    bottom = base.TEXT[3] - 10
    sky["baseline"] = bottom - 6
    # The Sun's headline keeps room for the year's curve: Next and Up ahead take turns first
    year = h["kind"] == "sun" and h["stats"] and year_span(sky) >= 1
    bottom = draw_coming(d, sky, x0, width, y + (YEAR_ROOM if year else 0), bottom)
    if h["kind"] == "sun" and h["stats"]:
        draw_year(d, sky, x0, y + 20, width, bottom)
        return

    # How far away each thing named on the dome is, farthest first: a key to the dome, so
    # everything on one is on the other. Only in quiet moments, when the headline is the
    # Sun, the Moon or nothing: around a pass, a train, a shower or a balloon the panel
    # stays on it. And whole or not at all
    if h["kind"] not in (None, "sun", "moon"):
        return
    items = sorted(NAMED, key=lambda i: i[1])
    top, gap = y + 30, 64
    if not items or len(items) > int((bottom - 10 - top) / gap):
        return
    # A rail with a stop for each, like a transit line: each dot level with its own name
    rail, lx = x0 + 12, x0 + 44
    mid = RUNG.size * 0.62
    d.line((rail, top + mid, rail, top + (len(items) - 1) * gap + mid), fill=FRAME, width=8)
    for i, (name, km, _kind) in enumerate(reversed(items)):
        ly = top + i * gap
        d.ellipse((rail - 13, ly + mid - 13, rail + 13, ly + mid + 13), fill=THING)
        d.text((lx, ly), name, font=RUNG, fill=THING)
        nw = base.text_w(d, name, RUNG)
        d.text((lx + nw + 14, ly + RUNG.size - KM.size - 1), base.fit(d, fmt_km(km), KM, x1 - lx - nw - 14),
               font=KM, fill=SOFT)


def draw_coming(d, sky, x0, width, top, bottom):
    """Next and Up ahead at the foot of the panel, short term above long. Both when they
    fit; when they don't, one at a time, turning over every 10 minutes, on redraws the
    frame makes anyway; while something crosses the sky, only Next. Returns the new bottom."""
    h = sky["hero"]
    blocks = []
    for label, said in (("Next", h.get("next")), ("Up ahead", h.get("ahead"))):
        if said:
            blocks.append((label, coming_lines(d, label, said[0], said[1], width)))
    gap = 16
    need = sum(len(lines) * (RUNG.size + 8) for _, lines in blocks) + gap * (len(blocks) - 1)
    if len(blocks) == 2 and (live(sky) or need > bottom - top - 40):
        blocks = blocks[:1] if live(sky) else [blocks[int(sky["t"] // 600) % 2]]
    y = bottom
    for label, lines in reversed(blocks):
        for i, (ln, f) in enumerate(reversed(lines)):
            y -= f.size + 8
            if i == len(lines) - 1 and ln.startswith(label):
                # The label a step down, so what's coming reads first
                d.text((x0, y), label, font=f, fill=SOFT)
                d.text((x0 + base.text_w(d, label, f), y), ln[len(label):], font=f, fill=THING)
            else:
                d.text((x0, y), ln, font=f, fill=THING)
            if i == 0 and label == blocks[-1][0]:
                sky["baseline"] = y + f.getmetrics()[0]
        y -= gap
    return y - 8 if blocks else bottom


def coming_lines(d, label, what, when, width):
    """One line if it fits at 34 px or more ("Next: ISS 8:49 tonight"). Else two, never
    breaking inside what or when: what beside the label and when below it ("Next: ISS
    overhead / 8:01 this evening"), or when beside the label and what below it ("Up ahead in
    9 days: / Saturn at its brightest"), whichever fits bigger."""
    def fit(*lines):
        f = base.fit_font(d, max(lines, key=lambda ln: base.text_w(d, ln, base.font(TF["name"], RUNG.size))),
                       TF["name"], RUNG.size, width, floor=CAPS.size)
        return [(ln, f) for ln in lines] if all(base.text_w(d, ln, f) <= width for ln in lines) else None
    one = fit("%s: %s %s" % (label, what, when))
    two = [lines for lines in (fit("%s: %s" % (label, what), when), fit("%s %s:" % (label, when), what)) if lines]
    return one or (max(two, key=lambda lines: lines[0][1].size) if two else
                   base.wrap(d, "%s: %s %s" % (label, what, when), TF["name"], RUNG.size, width, floor=CAPS.size)[:2])


def live(sky):
    """A pass or a train crossing right now."""
    t, tr = sky["t"], sky.get("train")
    return any(ps["rise"] <= t <= ps["set"] for _, ps in sky.get("passes", [])) or \
        bool(tr and tr["start"] <= t <= tr["end"])


def render(data, t, note=None):
    sky = build(data, t)
    sky["hero"] = hero(sky)
    img = base.CANVAS = Image.new("L", (base.W, base.H), GROUND)
    d = base.CachedDraw(img)
    draw_dome(img, d, sky)
    draw_panel(d, sky)
    if note:
        # Bottom corner beside the dome, which the circle leaves empty, on the Next line's baseline
        foot = sky.get("baseline", base.TEXT[3] - 16)
        d.text((SKY_BOX[2] - base.text_w(d, note, NOTE), foot - NOTE.getmetrics()[0]), note, font=NOTE, fill=SOFT)
    return img, sky


def layout():
    """The text panel on config "panel_side" (left unless it says right), the dome in the
    rest. Everything on the dome's rim is lettering (compass points,
    rise times), so the dome keeps to TEXT."""
    global PANEL_X, PANEL_R, DOME_X, DOME_Y, DOME_R, SKY_BOX
    t = base.TEXT
    pw = max(base.PANEL_W_CFG or 0, SKY_PANEL_W)
    if base.PANEL_SIDE == "left":
        PANEL_X, PANEL_R = t[0] + 8, t[0] + pw
        SKY_BOX = (PANEL_R + 24, t[1], t[2], t[3])
    else:
        PANEL_X, PANEL_R = t[2] - pw, t[2] - 8
        SKY_BOX = (t[0], t[1], PANEL_X - 24, t[3])
    # The compass letters sit on the horizon itself, in gaps cut in the line, so the dome
    # only needs room for half a letter outside it
    DOME_R = int(min(SKY_BOX[2] - SKY_BOX[0], SKY_BOX[3] - SKY_BOX[1]) / 2 - 26)
    DOME_X = (SKY_BOX[0] + SKY_BOX[2]) // 2
    DOME_Y = (SKY_BOX[1] + SKY_BOX[3]) // 2


# ---------- a gift ----------

# A letter to whoever unwraps the frame, shown in place of the sky until the first press of
# the power button. Put there by tools/gift.sh; never deployed, so a deploy can't bring it back
GIFT_PATH = os.path.join(HERE, "gift.txt")
GIFT_SEEN = os.path.join(HERE, "gift.seen")
GIFT_DAY = os.path.join(HERE, "gift.date")  # the day it was first opened: the day it was given
GIFT_NEXT = "Next: press the power button to see your sky"


def read_gift(path=None):
    """Paragraphs split by blank lines: the first is the greeting, the last the sign-off
    (kept line for line), the rest the letter. Typewriter quotes and dashes come out as
    the real thing."""
    try:
        with open(path or GIFT_PATH, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    for a, b in (("'", "’"), (" - ", " — "), ("\n-", "\n— "), ("\n—  ", "\n— ")):
        text = text.replace(a, b)
    paras = [p.strip() for p in text.replace("\r", "").split("\n\n") if p.strip()]
    return paras or None


def gift_returns(now):
    """Every year on the day it was given, the letter is back on the screen. Opening it
    stamps gift.seen with the time, so a day never brings it back twice."""
    try:
        with open(GIFT_DAY) as f:
            given = f.read().strip()
        opened = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(GIFT_SEEN)))
    except OSError:
        return
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    if given[5:] == today[5:] and opened < today:
        try:
            os.replace(GIFT_SEEN, GIFT_PATH)
        except OSError:
            pass


def gift_lines(d, text, f, width):
    """Word-wrapped, never leaving one word alone on a paragraph's last line."""
    words = text.split()
    if len(words) > 2:
        words[-2:] = [words[-2] + " " + words[-1]]
    return [ln.replace(" ", " ") for ln, _ in base.wrap(d, " ".join(words), TF["light"], f.size, width)]


def gift_rows(d, paras, n):
    """The letter on a grid of n equal rows filling the text box: every baseline on a row,
    every gap a whole empty row, the greeting two rows tall, and the last row for the Next
    line, where every sky screen has it. None if it doesn't fit."""
    top, bottom = base.TEXT[1], base.TEXT[3]
    u = (bottom - top) / float(n)
    body = base.font(TF["light"], int(round(u / 1.42)))
    sign = base.font(TF["head"], int(round(u * 0.86)))
    greet = base.font(TF["head"], int(round(u * 1.72)))
    width = base.TEXT[2] - base.TEXT[0]
    rows = [(2, paras[0], greet, HERO), (1, None, None, None)]
    *letter, signoff = paras[1:] if len(paras) > 2 else paras[1:] + [""]
    for i, para in enumerate(letter):
        if i:
            rows.append((1, None, None, None))
        rows += [(1, ln, body, THING) for ln in gift_lines(d, " ".join(para.split()), body, width)]
    if signoff:
        rows.append((1, None, None, None))
        for ln in signoff.split("\n"):
            if base.text_w(d, ln, sign) > width:
                return None
            rows.append((1, ln.strip(), sign, HERO))
    if base.text_w(d, paras[0], greet) > width or sum(r[0] for r in rows) > n - 2:
        return None
    return u, body, rows


def render_gift(paras):
    img = base.CANVAS = Image.new("L", (base.W, base.H), GROUND)
    d = ImageDraw.Draw(img)
    # The biggest type that fits: the fewest rows, but never a body bigger than the sky's
    # own labels (44) nor smaller than what reads across a room (34)
    fits = (gift_rows(d, paras, n) for n in range(12, 30))
    fit = next((f for f in fits if f and NOTE.size <= f[1].size <= LABEL.size), None)
    if not fit:
        raise ValueError("the letter is too long for one screen")
    u, body, rows = fit
    # Each row's baseline sits where a capital of the body type is centered in it
    drop = (u + body.getbbox("H")[3] - body.getbbox("H")[1]) / 2.0
    x, r = base.TEXT[0], 0
    for span, s, f, fill in rows:
        r += span
        if s:
            d.text((x, base.TEXT[1] + (r - 1) * u + drop), s, font=f, fill=fill, anchor="ls")
    # Beside the greeting, three stars in the dome's own marks: a bright one that twinkles
    # and two smaller, joined as a constellation: the sky frame, signing the letter
    if base.TEXT[2] - x - base.text_w(d, rows[0][1], rows[0][2]) > 3.4 * u:
        cx, cy = base.TEXT[2] - 0.5 * u, base.TEXT[1] + 0.62 * u
        stars = ((cx, cy), (cx - 1.25 * u, cy + 0.95 * u), (cx - 2.55 * u, cy + 0.55 * u))
        d.line(stars, fill=FRAME, width=5, joint="curve")
        for (sx, sy), rr in zip(stars[1:], (0.16 * u, 0.12 * u)):
            d.ellipse((sx - rr - 6, sy - rr - 6, sx + rr + 6, sy + rr + 6), fill=GROUND)
            d.ellipse((sx - rr, sy - rr, sx + rr, sy + rr), fill=THING)
        icons.paste(img, icons.glyph("sparkle", int(u * 0.95), HERO, 0, 8), cx, cy, GROUND)
    nf = base.fit_font(d, GIFT_NEXT, TF["name"], body.size, base.TEXT[2] - x, floor=30)
    d.text((x, base.TEXT[3] - u + drop), GIFT_NEXT, font=nf, fill=THING, anchor="ls")
    return img


# ---------- live data ----------

CELESTRAK = "https://celestrak.org/NORAD/elements/gp.php?GROUP=%s&FORMAT=csv"
SONDEHUB = "https://api.v2.sondehub.org/sondes?lat=%.4f&lon=%.4f&distance=250000&last=1800"
ORBITS_PATH = os.path.join(HERE, "orbits.csv")
BALLOON_PATH = os.path.join(HERE, "balloon.json")
ORBITS_MAX_AGE = 20 * 3600    # CelesTrak asks for no more than one download every 2 hours
ORBITS_RETRY_S = 3 * 3600     # after a failed download, keep the old orbits (good for days)
# Radiosondes go up an hour before 00 and 12 UTC everywhere (7 am and 7 pm at Buffalo in
# summer, 6 in winter); a flight is up about two hours, then falls. In UTC hours
BALLOON_WINDOWS = ((10.75, 14.0), (22.75, 26.0))
# Outside the windows, one look every 3 hours: research flights go up off the schedule, and
# pico balloons drift through at any hour. Every 30 minutes while a pico is in our sky
SONDE_CHECK_S = 3 * 3600
BALLOON_FETCH_S = 300         # while a balloon is up, on battery
WINDOW_CHECK_S = 900
PICO_CHECK_S = 1800
# Cloud cover for a shower night, to a tenth of a degree (the forecast's grid is coarser)
OPEN_METEO = ("https://api.open-meteo.com/v1/forecast?latitude=%.1f&longitude=%.1f"
              "&hourly=cloud_cover&forecast_days=2&timezone=GMT")
CLOUD_CHECK_S = 6 * 3600
AMATEUR = "https://api.v2.sondehub.org/amateur?lat=%.4f&lon=%.4f&distance=250000&last=7200"


def fetch_orbits(session, now):
    """The space stations, and the newest Starlink launch of the last 30 days: the one most
    likely to still be a train of lights. A few hundred objects instead of the whole fleet's
    ten thousand. CSV (OMM), not TLE: CelesTrak has no TLEs past catalog number 99999, which
    every launch since mid-2026 is. train_pass() decides whether it still looks like a train."""
    got = {}
    for group in ("stations", "last-30-days"):
        r = session.get(CELESTRAK % group, timeout=30)
        r.raise_for_status()
        if not r.text.startswith("OBJECT_NAME"):
            raise ValueError("not CelesTrak CSV: %r" % r.text[:60])
        got[group] = list(csv.DictReader(io.StringIO(r.text)))
    keep = [row for row in got["stations"] if row.get("OBJECT_NAME") in ("ISS (ZARYA)", "CSS (TIANHE)")]
    if not keep:
        raise ValueError("no ISS in CelesTrak's stations")
    # A download cut off mid-row leaves fields missing (None): skip those rows
    starlink = [row for row in got["last-30-days"]
                if (row.get("OBJECT_NAME") or "").startswith("STARLINK") and len(row.get("OBJECT_ID") or "") >= 8]
    if starlink:
        # OBJECT_ID is the launch: 2026-159A is the first object of 2026's 159th
        newest = max(row["OBJECT_ID"][:8] for row in starlink)
        keep += [row for row in starlink if row["OBJECT_ID"][:8] == newest]
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=list(keep[0]), lineterminator="\n", extrasaction="ignore")
    w.writeheader()
    w.writerows(keep)
    text = out.getvalue()
    if not any(name.startswith("ISS") for name, _ in astro.read_orbits(text)):
        raise ValueError("CelesTrak's ISS row doesn't parse")
    try:
        with open(ORBITS_PATH + ".tmp", "w") as f:
            f.write(text)
        os.replace(ORBITS_PATH + ".tmp", ORBITS_PATH)
    except OSError:
        pass  # Drive Mode: keep them in memory, the next download saves them
    return text


def in_balloon_window(now):
    h = time.gmtime(now).tm_hour + time.gmtime(now).tm_min / 60.0
    return any(a <= h < b or a <= h + 24 < b for a, b in BALLOON_WINDOWS)


def fetch_balloon(session, now, balloon):
    """The nearest radiosonde heard in the last half hour, its track built up one fetch at a
    time (5 minutes apart is enough to show the wind turning with height)."""
    r = session.get(SONDEHUB % (base.HOME_LAT, base.HOME_LON), timeout=20)
    r.raise_for_status()
    fresh = []
    for f in answer_rows(r):
        try:
            when = calendar.timegm(time.strptime(f["datetime"][:19], "%Y-%m-%dT%H:%M:%S"))
            fix = (float(f["lat"]), float(f["lon"]), float(f["alt"]))
            serial = str(f["serial"])
        except (KeyError, TypeError, ValueError):
            continue
        if now - when < 900:
            fresh.append((base.distance_bearing(base.HOME_LAT, base.HOME_LON, fix[0], fix[1])[0], when, fix, serial, f))
    if not fresh:
        return balloon if fresh_balloon(balloon, now) else None
    _, when, (lat, lon, alt), serial, f = min(fresh, key=lambda x: x[0])
    if not balloon or balloon.get("serial") != serial or not balloon.get("track"):
        balloon = dict(serial=serial, track=[])
    if not balloon["track"] or when > balloon["track"][-1][0]:
        balloon["track"].append([round(when), round(lat, 4), round(lon, 4), round(alt)])
    vel = f.get("vel_v")
    balloon["vel_v"] = vel if isinstance(vel, (int, float)) else None
    return balloon


def answer_rows(r):
    """The per-balloon records of a SondeHub answer, whatever shape came back: an error
    message or a list instead of the usual {id: record} gives nothing, never a crash."""
    data = r.json()
    if not isinstance(data, dict):
        return []
    rows = []
    for v in data.values():
        if isinstance(v, dict) and "lat" not in v:
            # The amateur feed nests {id: {time: record}}: the latest record
            v = next((w for w in reversed(list(v.values())) if isinstance(w, dict)), None)
        if isinstance(v, dict):
            rows.append(v)
    return rows


def fresh_balloon(b, now):
    """A weather balloon heard in the last 20 minutes and still in the air. An older one has
    landed or gone, and so has one that burst and is under a kilometer: a sonde keeps
    transmitting on the ground, and receivers near where it came down keep hearing it."""
    if not (b and b.get("track") and now - b["track"][-1][0] < 1200):
        return False
    alt = b["track"][-1][3]
    return not (alt < 1000 and peak_alt(b) > alt + 1000)


def peak_alt(b):
    """The highest it got, from its own track (a few fixes a minute apart, so within a few
    hundred meters of the burst)."""
    return max(fix[3] for fix in b["track"])


def fetch_amateur(session, now):
    """The nearest amateur balloon aloft within 250 km and heard in the last two hours. The
    long-duration picos report how many days they've been up."""
    r = session.get(AMATEUR % (base.HOME_LAT, base.HOME_LON), timeout=20)
    r.raise_for_status()
    near = []
    for f in answer_rows(r):
        try:
            when = calendar.timegm(time.strptime(f["datetime"][:19], "%Y-%m-%dT%H:%M:%S"))
            lat, lon, alt = float(f["lat"]), float(f["lon"]), float(f["alt"])
            if now - when > 7200 or alt < 3000:
                continue
            near.append((base.distance_bearing(base.HOME_LAT, base.HOME_LON, lat, lon)[0], dict(
                lat=round(lat, 4), lon=round(lon, 4),
                alt=round(alt), when=when, days=int(float(f["days_aloft"])) if f.get("days_aloft") else None)))
        except (KeyError, TypeError, ValueError):
            continue
    return min(near, key=lambda n: n[0])[1] if near else None


def fetch_clouds(session, now):
    """Hourly cloud cover for the next two days, as [[epoch, percent]]."""
    r = session.get(OPEN_METEO % (base.HOME_LAT, base.HOME_LON), timeout=20)
    r.raise_for_status()
    hourly = r.json()["hourly"]
    hours = []
    for when, pct in zip(hourly["time"], hourly["cloud_cover"]):
        if isinstance(pct, (int, float)):
            hours.append([calendar.timegm(time.strptime(when, "%Y-%m-%dT%H:%M")), pct])
    return {"at": now, "hours": hours}


def note_failure(what, e, reached, dead):
    """Sort a failed request: no connection at all (the link may be dead), or a server that
    answered badly, slowly or with a certificate we can't check (the link is fine)."""
    print("%s fetch failed: %r" % (what, e), flush=True)
    link = isinstance(e, (requests.ConnectionError, requests.ConnectTimeout)) and \
        not isinstance(e, requests.exceptions.SSLError)
    return (reached, dead or e) if link else (True, dead)


def next_balloon_window(now):
    """Epoch when the next balloon window opens."""
    day = now - now % 86400
    starts = [day + k * 86400 + a * 3600 for k in (0, 1) for a, _ in BALLOON_WINDOWS]
    return min(t for t in starts if t > now)


class Frame:
    """The sky frame for loop.run. Wi-Fi goes on only when something is due: orbits once a
    day, balloons around their launches (every 15 minutes until one is up, then every 5)
    and every 3 hours otherwise. The rest is computed here, so in between it just redraws,
    every 10 minutes, or every minute while something crosses. At night (config "night")
    it fetches nothing and redraws at each half-hourly wake."""

    def __init__(self, args):
        self.args, self.log, self.fetch_log = args, {}, {}
        self.sky = {}
        try:
            with open(ORBITS_PATH) as f:
                self.orbits = f.read()
            self.orbits_at = os.path.getmtime(ORBITS_PATH)
        except OSError:
            self.orbits, self.orbits_at = "", 0
        self.orbits_tried = 0
        self.sondes_at, self.amateur = 0, None
        self.clouds, self.clouds_tried = None, 0
        try:
            with open(BALLOON_PATH) as f:
                self.balloon = json.load(f)
        except (OSError, ValueError):
            self.balloon = None

    def configure(self, args):
        cfg = base.load_config(args)
        layout()
        return cfg

    def orbits_due(self):
        return max(self.orbits_at + ORBITS_MAX_AGE, self.orbits_tried + ORBITS_RETRY_S)

    def fetch(self, session, now):
        """Orbits when a day old, the balloons around launches and every few hours. Only when
        nothing at all got through does it raise, so the loop backs off and recovers Wi-Fi;
        one server down, or a bad answer, just waits for next time."""
        self.fetch_log = {}
        reached, dead = False, None
        if now >= self.orbits_due():
            # Before the request: a connection dropped mid-download must not mean another
            # download straight away (CelesTrak asks for one every 2 hours at most)
            self.orbits_tried = now
            try:
                self.orbits, self.orbits_at = fetch_orbits(session, now), now
                self.fetch_log["orbits"] = reached = 1
            except Exception as e:
                reached, dead = note_failure("orbits", e, reached, dead)
        if self.balloons_due(now) <= now:
            try:
                self.balloon = fetch_balloon(session, now, self.balloon)
                base.write_json(BALLOON_PATH, self.balloon)
                self.fetch_log["balloon"] = int(bool(self.balloon))
                self.amateur = fetch_amateur(session, now)
                self.fetch_log["pico"] = int(bool(self.amateur))
                reached = True
                self.sondes_at = now
            except Exception as e:
                reached, dead = note_failure("balloons", e, reached, dead)
                if reached:
                    self.sondes_at = now
        if self.clouds_due(now) <= now:
            self.clouds_tried = now
            try:
                self.clouds = fetch_clouds(session, now)
                self.fetch_log["clouds"] = reached = 1
            except Exception as e:
                reached, dead = note_failure("clouds", e, reached, dead)
        if dead and not reached:
            raise dead
        if self.args.save_sample:
            with open(self.args.save_sample, "w") as f:
                json.dump(self.data(now), f)

    def data(self, now):
        return {"time": now, "orbits": self.orbits, "balloon": self.balloon, "amateur": self.amateur,
                "clouds": self.clouds}

    def clouds_due(self, now):
        """The forecast for a shower night, from the morning before to its end, every 6
        hours: a few fetches a year. Never when no shower worth showing is near."""
        due = []
        for ev in shower_list(now):
            opens = ev["start"] - 12 * 3600
            if opens <= now < ev["end"]:
                due.append(max(opens, self.clouds_tried + CLOUD_CHECK_S))
            elif now < opens:
                due.append(opens)
        return min(due) if due else now + 86400

    def balloons_due(self, now):
        # In a launch window, every 15 minutes until one is up; then every 5 to draw its climb,
        # every minute on a charger, where Wi-Fi is up anyway
        if fresh_balloon(self.balloon, now):
            return self.sondes_at + (60 if getattr(self, "plugged", False) else BALLOON_FETCH_S)
        if in_balloon_window(now):
            return self.sondes_at + WINDOW_CHECK_S
        return min(next_balloon_window(now), self.sondes_at + (PICO_CHECK_S if self.amateur else SONDE_CHECK_S))

    def next_due(self, now):
        return min(self.orbits_due(), self.balloons_due(now), self.clouds_due(now))

    def fetch_every(self, now):
        return max(60, self.next_due(now) - now)

    def render(self, now, fetched_at, note=None):
        gift_returns(now)
        gift = read_gift()
        if gift:
            self.sky, self.log = {}, {"gift": 1}
            return render_gift(gift)
        img, self.sky = render(self.data(now), now, note)
        self.log = {"things": len(self.sky["things"])}
        return img

    @property
    def idle_redraw_s(self):
        # A letter doesn't change: no redraws for it beyond the fetches
        return None if os.path.exists(GIFT_PATH) else 600

    def pressed(self):
        """The first press of the power button opens the gift: the letter is put away
        (gift.seen, until its day comes round again) and the sky takes its place."""
        if not os.path.exists(GIFT_PATH):
            return False
        try:
            os.replace(GIFT_PATH, GIFT_SEEN)
            os.utime(GIFT_SEEN)
            if not os.path.exists(GIFT_DAY):
                with open(GIFT_DAY, "w") as f:
                    f.write(time.strftime("%Y-%m-%d"))
        except OSError:
            # Drive Mode has /mnt/us: unless the letter moved, the press does what it always does
            return os.path.exists(GIFT_SEEN)
        return True

    def mood(self, now):
        """Live while a pass or train crosses; soon when the headline is something on its way
        within the half hour; otherwise calm."""
        if live(dict(self.sky, t=now)):
            return "live"
        h = self.sky.get("hero", {})
        return "soon" if "wonder" in h and 0 < h["start"] - now <= 1800 else "calm"

    def screen_key(self):
        """What the screen says, with degrees to the nearest 5 so a Moon climbing a degree
        doesn't count as news (the 15-minute redraw catches it up), and what's on the dome.
        First the moment, whose change is worth a flash: the headline, and a balloon's burst."""
        if not self.sky:
            return ("gift",)  # the letter, which never changes
        h = self.sky["hero"]
        # A balloon bursting is a new moment, as good as a new headline
        moment = (h["head"], any(th["kind"] == "balloon" and not th["rising"] for th in self.sky["things"])
                  if h["kind"] == "balloon" else None)

        def coarse(v):
            return "%d°" % (5 * round(int(v[:-1]) / 5.0)) if v.endswith("°") and v[:-1].lstrip("-").isdigit() else v
        return (moment, tuple((coarse(v), lab) for v, lab in h.get("stats", [])), h.get("foot"),
                (h.get("next"), h.get("ahead")),
                tuple(sorted(th["kind"] + th["name"] for th in self.sky["things"] if not th.get("below"))),
                bool(self.sky.get("train")), tuple(ps["rise"] for _, ps in self.sky.get("passes", [])
                                                   if ps["rise"] <= self.sky["t"] + 3600))

    def moving(self, now):
        """Minute redraws while a pass or train is on: they cross the sky in minutes. Not for
        balloons, which only move when new data comes in, every 5 minutes with the fetch."""
        tr = self.sky.get("train")
        return any(ps["rise"] - 1800 <= now <= ps["set"] for _, ps in self.sky.get("passes", [])) or \
            bool(tr and tr["start"] - 900 <= now <= tr["end"])

    def in_night(self, now):
        return base.in_night(now)

    def next_morning(self, now):
        return base.next_morning(now)

    def night_key(self, now, mode):
        return mode + str(int(now // loop.NIGHT_WAKE_S)) + ("gift" if os.path.exists(GIFT_PATH) else "")

    def render_night(self, now, mode):
        return self.render(now, 0, note="Battery low" if mode == "low" else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="render one frame and exit")
    ap.add_argument("--out", help="write PNG here instead of pushing to the screen")
    ap.add_argument("--sample", help="render from a saved {time, orbits or tle, balloon} JSON instead of the network")
    ap.add_argument("--save-sample", help="also write the fetched data to this JSON (for design testing)")
    ap.add_argument("--time", type=float, help="with --sample: unix time to render instead of the sample's")
    ap.add_argument("--heading", type=float, help="compass direction the viewer faces (0-359)")
    ap.add_argument("--rotate", type=int, choices=(0, 90, 180, 270), help="clockwise turn onto the panel")
    ap.add_argument("--panel", help="preview another Kindle's panel, portrait WxH (758x1024 for a PW2)")
    ap.add_argument("--config", help="read this instead of the config.json beside sky.py")
    ap.add_argument("--gift", help="preview this gift.txt instead of the sky")
    args = ap.parse_args()
    args.style = None
    if args.panel:
        loop.PANEL = tuple(int(v) for v in args.panel.split("x"))
    base.load_config(args)
    layout()

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    if args.gift:
        loop.turn(render_gift(read_gift(args.gift)), base.ROTATE).save(args.out or "/tmp/sky.pgm")
        return

    if args.sample:
        with open(args.sample) as f:
            data = json.load(f)
        img, sky = render(data, args.time or data["time"])
        path = args.out or "/tmp/sky.pgm"
        loop.turn(img, base.ROTATE).save(path)
        print(path, "sun %.1f°" % sky["sun_el"], len(sky["things"]), "things")
        return

    loop.run(Frame(args), args)


if __name__ == "__main__":
    main()
