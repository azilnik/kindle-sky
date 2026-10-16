"""Where things are in the sky over home, in plain Python so it runs on the Kindle.

Low-precision formulas throughout (Astronomical Almanac sun and moon, JPL's approximate
Keplerian elements for planets): good to a fraction of a degree, which is a few pixels
on the dome. Satellites use sgp4, which falls back to pure Python without its C module.
"""

import functools
import io
import math
import os
import sys

# sgp4 is vendored as its pure-Python modules (MIT, vendor/sgp4/LICENSE): the Kindle's
# Python has no compiler for its C extension, and nothing to install is simpler
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
from sgp4 import omm  # noqa: E402
from sgp4.api import Satrec  # noqa: E402

R_EARTH = 6378.137
AU_KM = 149597870.7
D = math.pi / 180


def jd(t):
    return t / 86400.0 + 2440587.5


def gmst(t):
    """Greenwich mean sidereal time, degrees."""
    return (280.46061837 + 360.98564736629 * (jd(t) - 2451545.0)) % 360


def alt_az(ra, dec, t, lat, lon):
    """Equatorial (deg) to (altitude, azimuth from north through east), degrees."""
    ha = (gmst(t) + lon - ra) * D
    dec, lat = dec * D, lat * D
    alt = math.asin(math.sin(dec) * math.sin(lat) + math.cos(dec) * math.cos(lat) * math.cos(ha))
    az = math.atan2(-math.sin(ha) * math.cos(dec),
                    math.cos(lat) * math.sin(dec) - math.sin(lat) * math.cos(dec) * math.cos(ha))
    return alt / D, (az / D) % 360


def _ecl_to_eq(lam, beta, eps):
    lam, beta, eps = lam * D, beta * D, eps * D
    ra = math.atan2(math.sin(lam) * math.cos(eps) - math.tan(beta) * math.sin(eps), math.cos(lam))
    dec = math.asin(math.sin(beta) * math.cos(eps) + math.cos(beta) * math.sin(eps) * math.sin(lam))
    return (ra / D) % 360, dec / D


def sun(t):
    """(ra, dec, ecliptic longitude) in degrees."""
    n = jd(t) - 2451545.0
    L = 280.460 + 0.9856474 * n
    g = (357.528 + 0.9856003 * n) * D
    lam = L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)
    ra, dec = _ecl_to_eq(lam, 0, 23.439 - 0.0000004 * n)
    return ra, dec, lam % 360


def moon(t):
    """(ra, dec, distance km, illuminated fraction, waxing)."""
    lam, beta, dist = moon_ecliptic(t)
    T = (jd(t) - 2451545.0) / 36525
    ra, dec = _ecl_to_eq(lam, beta, 23.439 - 0.013 * T)
    elong = (lam - sun(t)[2]) % 360
    return ra, dec, dist, (1 - math.cos(elong * D)) / 2, elong < 180


def moon_ecliptic(t):
    """(longitude, latitude, distance km) along the Sun's yearly path: the latitude is how far
    the Moon passes from Earth's shadow at a full moon, so whether there's an eclipse."""
    T = (jd(t) - 2451545.0) / 36525

    def s(a, b):
        return math.sin((a + b * T) * D)

    def c(a, b):
        return math.cos((a + b * T) * D)

    lam = (218.32 + 481267.881 * T + 6.29 * s(135.0, 477198.87) - 1.27 * s(259.3, -413335.36)
           + 0.66 * s(235.7, 890534.22) + 0.21 * s(269.9, 954397.74) - 0.19 * s(357.5, 35999.05)
           - 0.11 * s(186.5, 966404.03))
    beta = 5.13 * s(93.3, 483202.02) + 0.28 * s(228.2, 960400.89) - 0.28 * s(318.3, 6003.15) - 0.17 * s(217.6, -407332.21)
    par = (0.9508 + 0.0518 * c(134.9, 477198.85) + 0.0095 * c(259.2, -413335.38)
           + 0.0078 * c(235.7, 890534.23) + 0.0028 * c(269.9, 954397.70))
    return lam % 360, beta, R_EARTH / math.sin(par * D)


def moon_alt_az(t, lat, lon):
    """Topocentric: the moon is close enough that parallax moves it up to a degree."""
    ra, dec, dist, frac, waxing = moon(t)
    alt, az = alt_az(ra, dec, t, lat, lon)
    return alt - math.degrees(math.asin(R_EARTH / dist)) * math.cos(alt * D), az, dist, frac, waxing


# JPL "Approximate Positions of the Planets", 1800-2050: a e I L long.peri long.node, then rates per century
ELEMENTS = {
    "Venus": ((0.72333566, 0.00677672, 3.39467605, 181.97909950, 131.60246718, 76.67984255),
              (0.00000390, -0.00004107, -0.00078890, 58517.81538729, 0.00268329, -0.27769418)),
    "Earth": ((1.00000261, 0.01671123, -0.00001531, 100.46457166, 102.93768193, 0.0),
              (0.00000562, -0.00004392, -0.01294668, 35999.37244981, 0.32327364, 0.0)),
    "Mars": ((1.52371034, 0.09339410, 1.84969142, -4.55343205, -23.94362959, 49.55953891),
             (0.00001847, 0.00007882, -0.00813131, 19140.30268499, 0.44441088, -0.29257343)),
    "Jupiter": ((5.20288700, 0.04838624, 1.30439695, 34.39644051, 14.72847983, 100.47390909),
                (-0.00011607, -0.00013253, -0.00183714, 3034.74612775, 0.21252668, 0.20469106)),
    "Saturn": ((9.53667594, 0.05386179, 2.48599187, 49.95424423, 92.59887831, 113.66242448),
               (-0.00125060, -0.00050991, 0.00193609, 1222.49362201, -0.41897216, -0.28867794)),
}
PLANETS = ("Venus", "Mars", "Jupiter", "Saturn")


def _helio(name, T):
    (a, e, i, L, wbar, node), rate = ELEMENTS[name]
    a, e, i, L, wbar, node = (x + r * T for x, r in zip((a, e, i, L, wbar, node), rate))
    w, M = (wbar - node) * D, ((L - wbar + 180) % 360 - 180) * D
    E = M + e * math.sin(M)
    for _ in range(6):
        E -= (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
    x1, y1 = a * (math.cos(E) - e), a * math.sqrt(1 - e * e) * math.sin(E)
    i, node = i * D, node * D
    cw, sw, cn, sn, ci, si = math.cos(w), math.sin(w), math.cos(node), math.sin(node), math.cos(i), math.sin(i)
    return ((cw * cn - sw * sn * ci) * x1 + (-sw * cn - cw * sn * ci) * y1,
            (cw * sn + sw * cn * ci) * x1 + (-sw * sn + cw * cn * ci) * y1,
            sw * si * x1 + cw * si * y1)


def planet(name, t):
    """(ra, dec, distance km), geocentric."""
    T = (jd(t) - 2451545.0) / 36525
    p, e = _helio(name, T), _helio("Earth", T)
    x, y, z = p[0] - e[0], p[1] - e[1], p[2] - e[2]
    eps = 23.43928 * D
    y, z = y * math.cos(eps) - z * math.sin(eps), y * math.sin(eps) + z * math.cos(eps)
    return (math.atan2(y, x) / D) % 360, math.atan2(z, math.hypot(x, y)) / D, math.sqrt(x * x + y * y + z * z) * AU_KM


# ---------- satellites ----------

def read_orbits(text):
    """[(name, satellite)] from CelesTrak's OMM CSV, or from TLEs (the samples are TLEs).
    CSV because TLEs stop at catalog number 99999, and every launch since mid-2026 is past it."""
    if text.startswith("OBJECT_NAME"):
        out = []
        for fields in omm.parse_csv(io.StringIO(text)):
            sat = Satrec()
            try:
                omm.initialize(sat, fields)
            except (KeyError, TypeError, ValueError):
                continue  # one odd row costs one satellite, not the frame
            out.append((fields["OBJECT_NAME"], sat))
        return out
    rows = [r.rstrip() for r in text.splitlines() if r.strip()]
    return [(rows[i].strip(), Satrec.twoline2rv(rows[i + 1], rows[i + 2])) for i in range(0, len(rows) - 2, 3)]


@functools.lru_cache(maxsize=4)
def _observer(lat, lon, h_km=0.17):
    """WGS84 geodetic to Earth-fixed km."""
    f = 1 / 298.257223563
    e2 = f * (2 - f)
    la, lo = lat * D, lon * D
    n = R_EARTH / math.sqrt(1 - e2 * math.sin(la) ** 2)
    return ((n + h_km) * math.cos(la) * math.cos(lo), (n + h_km) * math.cos(la) * math.sin(lo),
            (n * (1 - e2) + h_km) * math.sin(la))


def sat_look(sat, t, lat, lon):
    """(elevation, azimuth, range km, height km, sunlit) or None if sgp4 gives up."""
    j = jd(t)
    err, r, _ = sat.sgp4(math.floor(j - 0.5) + 0.5, j - 0.5 - math.floor(j - 0.5))
    if err:
        return None
    # TEME is close enough to Earth-fixed once turned by sidereal time (no polar motion)
    g = gmst(t) * D
    x = r[0] * math.cos(g) + r[1] * math.sin(g)
    y = -r[0] * math.sin(g) + r[1] * math.cos(g)
    z = r[2]
    ox, oy, oz = _observer(lat, lon)
    dx, dy, dz = x - ox, y - oy, z - oz
    la, lo = lat * D, lon * D
    east = -math.sin(lo) * dx + math.cos(lo) * dy
    north = -math.sin(la) * math.cos(lo) * dx - math.sin(la) * math.sin(lo) * dy + math.cos(la) * dz
    up = math.cos(la) * math.cos(lo) * dx + math.cos(la) * math.sin(lo) * dy + math.sin(la) * dz
    rng = math.sqrt(dx * dx + dy * dy + dz * dz)
    # Sunlit unless inside Earth's shadow cylinder
    s = _sun_dir(int(t // 60))
    along = r[0] * s[0] + r[1] * s[1] + r[2] * s[2]
    perp = math.sqrt(max(0.0, r[0] ** 2 + r[1] ** 2 + r[2] ** 2 - along * along))
    lit = along > 0 or perp > R_EARTH
    return (math.asin(up / rng) / D, (math.atan2(east, north) / D) % 360, rng,
            math.sqrt(r[0] ** 2 + r[1] ** 2 + r[2] ** 2) - R_EARTH, lit)


@functools.lru_cache(maxsize=256)
def _sun_dir(minute):
    """Unit vector to the Sun, once a minute: it moves a quarter degree in that time, and
    working it out was half the cost of each satellite position."""
    sra, sdec, _ = sun(minute * 60)
    return (math.cos(sdec * D) * math.cos(sra * D), math.cos(sdec * D) * math.sin(sra * D), math.sin(sdec * D))


def next_pass(sat, t, lat, lon, horizon=10, span=6 * 3600, step=20):
    """The current or next pass above `horizon` degrees: dict of rise/peak/set times,
    azimuths, peak elevation, and the sky track as (t, el, az) samples. None if none in span.
    Coarse steps: the Kindle runs this in pure Python, and the sky frame keeps the answer
    (kept()) rather than searching again each frame."""
    track, start = [], t
    # Back up to catch a pass that's already underway
    while True:
        look = sat_look(sat, start - step, lat, lon)
        if not look or look[0] < horizon or t - start > 1200:
            break
        start -= step
    tt = start
    while tt < t + span:
        look = sat_look(sat, tt, lat, lon)
        if look and look[0] >= horizon:
            track.append((tt,) + look)
        elif track:
            break
        tt += step
    if not track:
        return None
    peak = max(track, key=lambda k: k[1])
    return {"rise": track[0][0], "rise_az": track[0][2], "peak": peak[0], "peak_el": peak[1],
            "set": track[-1][0], "set_az": track[-1][2], "track": track,
            "visible": any(k[5] for k in track) and sun_alt(peak[0], lat, lon) < -6}


def next_visible_pass(sat, t, lat, lon, span=24 * 3600):
    """The current or next pass you could actually see (sunlit satellite, dark sky)."""
    tt = t
    while tt < t + span:
        if sun_alt(tt, lat, lon) > -6:
            # No pass can be seen in daylight: go straight to dusk, less the length of a pass
            dusk = next((d for d in range(int(tt), int(t + span), 600) if sun_alt(d, lat, lon) < -6), None)
            if dusk is None:
                return None
            tt = max(tt, dusk - 900)
        ps = next_pass(sat, tt, lat, lon, span=t + span - tt, step=30)
        if not ps or ps["visible"]:
            return ps
        tt = ps["set"] + 60
    return None


def sun_alt(t, lat, lon):
    ra, dec, _ = sun(t)
    return alt_az(ra, dec, t, lat, lon)[0]
