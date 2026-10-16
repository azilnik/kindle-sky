#!/usr/bin/env python3
"""Run the real screen loop (loop.py) and sky frame on a fake clock, panel, power supply and
SondeHub, and check how the screen behaves: on a charger it should stay still until there's
something to see, and on battery do as it always has. Nothing touches the network or a
Kindle; a scenario takes seconds to a minute on a laptop.

Usage: uv run --python 3.9 --with pillow==9.0.1 --with requests python tools/simulate.py [-v] [scenario ...]
Every scenario by default; -v prints each screen update. Exits 1 if a check fails."""

import json
import math
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PLANES = os.path.join(HERE, "..", "planes")
sys.path.insert(0, PLANES)
os.environ["TZ"] = "EST5EDT,M3.2.0,M11.1.0"
time.tzset()

import loop  # noqa: E402
import power  # noqa: E402
import requests  # noqa: E402
import sky  # noqa: E402

import planes as P  # noqa: E402


def local(s):
    return time.mktime(time.strptime(s, "%Y-%m-%d %H:%M"))


def hhmm(t):
    return time.strftime("%-I:%M:%S", time.localtime(t))


# ---------- a radiosonde flight from Buffalo, the way they go ----------

LAUNCH = local("2026-09-25 07:00")
BUFFALO = (42.94, -78.72)
CLIMB_S = 6600   # 5 m/s to 33 km
FALL_S = 2400


def flight(t, site=BUFFALO, silent_after=None):
    """(lat, lon, alt m) of the sonde at t, or None when nobody hears it: before launch,
    after it goes quiet, or half an hour after landing."""
    dt = t - LAUNCH
    if dt < 0 or (silent_after and dt > silent_after) or dt > CLIMB_S + FALL_S + 1800:
        return None
    if dt <= CLIMB_S:
        alt = 180 + 5 * dt
    else:
        alt = max(180, 33180 * (1 - min(1.0, (dt - CLIMB_S) / float(FALL_S))) ** 1.6)
    east_km = min(dt, CLIMB_S + FALL_S) / 3600.0 * 30
    return site[0], site[1] + east_km / (111.32 * math.cos(math.radians(site[0]))), alt


# ---------- fakes ----------

class Sim:
    def __init__(self):
        self.clock = 0.0
        self.end = 0.0
        self.plugged = lambda t: True
        self.night = lambda t: False
        self.flight = flight
        self.vel_v = False
        self.hooks = []
        self.calls, self.shows, self.renders, self.log = [], [], [], []


SIM = Sim()


class Resp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class Session:
    headers = {}

    def get(self, url, timeout=None):
        what = url.split("?")[0].rsplit("/", 1)[-1]
        SIM.calls.append((SIM.clock, what))
        if what == "sondes":
            fix = SIM.flight(SIM.clock)
            if not fix:
                return Resp({})
            row = {"datetime": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(SIM.clock)),
                   "lat": fix[0], "lon": fix[1], "alt": fix[2], "serial": "S1234"}
            if SIM.vel_v:
                ahead = SIM.flight(SIM.clock + 1)
                row["vel_v"] = ahead[2] - fix[2] if ahead else 0
            return Resp({"S1234": row})
        if what == "amateur":
            return Resp({})
        raise AssertionError("unexpected fetch: " + url)


def sleep_until(t, suspend=False):
    if t >= SIM.end:
        raise SystemExit
    SIM.clock = max(SIM.clock + 1, t)
    for hook in SIM.hooks:
        hook()
    return "idle"


def install_fakes():
    time.time = lambda: SIM.clock
    time.sleep = lambda s: setattr(SIM, "clock", SIM.clock + s)
    power.sleep_until = sleep_until
    for name in ("set_governor", "wifi_up", "wifi_down", "set_frontlight", "reboot", "restart_wifid"):
        setattr(power, name, lambda *a, **k: 0.0)
    power.on_ac = lambda: SIM.plugged(SIM.clock)
    power.battery = lambda: ("100", "", "", "1" if SIM.plugged(SIM.clock) else "0")
    power.log = lambda kind, **kw: SIM.log.append((SIM.clock, kind, kw))
    loop.show = lambda path, flash: SIM.shows.append((SIM.clock, flash))
    loop.turn = lambda img, rotate: type("Img", (), {"save": lambda self, path: None})()
    P.in_night = lambda now: SIM.night(now)
    requests.Session = Session
    # The frame saves balloon.json beside itself: keep the simulated flight out of planes/
    sky.BALLOON_PATH = os.path.join(tempfile.mkdtemp(), "balloon.json")


class Args:
    once = False
    out = None
    heading = 235
    rotate = 0
    style = None
    config = None
    save_sample = None


def frame(start, sample):
    """A sky frame on a sample's orbits, everything fetched as of start except balloons."""
    with open(os.path.join(PLANES, "samples", "sky", sample + ".json")) as f:
        d = json.load(f)
    fr = sky.Frame(Args())
    fr.orbits, fr.orbits_at, fr.balloon = d.get("orbits") or d.get("tle", ""), start, None
    orig = fr.render

    def render(now, fetched_at, note=None):
        img = orig(now, fetched_at, note)
        b = next((th for th in fr.sky["things"] if th["kind"] == "balloon"), None)
        SIM.renders.append(dict(t=now, mood=fr.mood(now), head=fr.sky["hero"]["head"],
                                foot=fr.sky["hero"].get("foot"), alt=b and round(b["alt_km"], 1),
                                burst=bool(b and not b["rising"])))
        return img
    fr.render = render
    return fr


def run(fr, start, minutes):
    SIM.clock, SIM.end = start, start + minutes * 60
    try:
        loop.run(fr, Args())
    except SystemExit:
        pass


def flashes():
    return [t for t, flash in SIM.shows if flash]


# ---------- scenarios: each returns [(check, passed)] ----------

def s_flight():
    start = local("2026-09-25 06:40")
    run(frame(start, "midday"), start, 190)
    balloon = [r for r in SIM.renders if r["head"] == "Weather balloon"]
    first = balloon[0]["t"]
    burst = next(r["t"] for r in balloon if r["burst"])
    gone = next((r["t"] for r in SIM.renders if r["t"] > burst and r["head"] != "Weather balloon"), None)
    climbing = [t for t, _ in SIM.shows if first < t < burst]
    gap = sorted(b - a for a, b in zip(climbing, climbing[1:]))[len(climbing) // 2]
    sondes = [t for t, what in SIM.calls if what == "sondes" and first <= t <= burst]
    return [("one flash as the balloon takes the headline", first in flashes()),
            ("one flash at the burst", burst in flashes()),
            ("climbing, an update about every 3 minutes (median %ds)" % gap, 150 <= gap <= 240),
            ("a balloon is never live", all(r["mood"] != "live" for r in balloon)),
            ("no other flash while it climbs, but clearing ghosts", sum(first < t < burst for t in flashes()) <= 2),
            ("it leaves the headline once down (%s)" % (gone and hhmm(gone)), gone is not None),
            ("fetched every minute while it flies", len(sondes) >= (burst - first) / 60 * 0.9)]


def s_battery():
    SIM.plugged = lambda t: False
    start = local("2026-09-25 06:40")
    run(frame(start, "midday"), start, 190)
    fl = flashes()
    sondes = [t for t, what in SIM.calls if what == "sondes"]
    gap = min(b - a for a, b in zip(sondes, sondes[1:]))
    return [("on battery, a full flash every 30 minutes as before", all(b - a > 1700 for a, b in zip(fl, fl[1:]))),
            ("on battery, the balloon every 5 minutes (closest %ds)" % gap, gap >= 290)]


def s_near_landing():
    # Launched about 20 km from home and drifting east: it comes down above the horizon
    site = (P.HOME_LAT - 0.15, P.HOME_LON - 0.2)
    SIM.flight = lambda t: flight(t, site=site)
    start = local("2026-09-25 08:30")
    run(frame(start, "midday"), start, 120)
    down = [r for r in SIM.renders if r["head"] == "Weather balloon" and r["alt"] is not None and r["alt"] < 1.0]
    return [("a balloon down under 1 km nearby isn't shown", not down)]


def s_mid_fall(vel_v=False):
    SIM.vel_v = vel_v
    start = LAUNCH + CLIMB_S + 300
    run(frame(start, "midday"), start, 20)
    feet = [r["foot"] for r in SIM.renders if r["head"] == "Weather balloon"][:2]
    out = [("first heard falling, Falling by the second fetch: %s" % feet, "Falling" in feet),
           ("no launch place for one first heard high up", all(f in ("Climbing", "Falling") for f in feet))]
    if vel_v:
        out.append(("with a vertical speed, Falling from the first frame", feet[:1] == ["Falling"]))
    return out


def s_lost():
    SIM.flight = lambda t: flight(t, silent_after=3000)
    start = local("2026-09-25 07:30")
    run(frame(start, "midday"), start, 60)
    last = max(r["t"] for r in SIM.renders if r["head"] == "Weather balloon")
    return [("a balloon gone quiet leaves within 20 minutes (%s)" % hhmm(last), last - (LAUNCH + 3000) <= 1260),
            ("and its leaving flashes", any(t > last for t in flashes()))]


def s_unplug_mid_pass():
    off, on = local("2026-09-26 19:52"), local("2026-09-26 20:00")
    SIM.plugged = lambda t: not off <= t < on
    start = local("2026-09-26 19:00")
    run(frame(start, "iss_soon"), start, 75)
    unplugged = [r for r in SIM.renders if off <= r["t"] < on]
    after = [r for r in SIM.renders if on <= r["t"] < on + 240]
    return [("unplugged mid-pass, minute redraws (%d in 8 min)" % len(unplugged), 6 <= len(unplugged) <= 10),
            ("plugged back in, every 15 s again (%d in 4 min)" % len(after), len(after) >= 14)]


def s_clock_back():
    start = local("2026-09-25 13:00")
    jumped = []

    def jump():
        if not jumped and SIM.clock >= start + 1800:
            SIM.clock -= 7200
            jumped.append(SIM.clock)
    SIM.hooks.append(jump)
    run(frame(start, "midday"), start, 60)
    # The first update stamped earlier than the one before it is the first after the jump
    after = [t for i, (t, _) in enumerate(SIM.shows) if i and t < SIM.shows[i - 1][0]]
    return [("clock set back 2 h, a redraw within 15 minutes", bool(after) and after[0] - jumped[0] <= 900)]


def s_night_mid_live():
    SIM.night = lambda t: t >= local("2026-09-26 20:01")
    start = local("2026-09-26 19:55")
    run(frame(start, "iss_soon"), start, 20)
    return [("night falls mid-pass: the night picture, no crash", any(k == "night_draw" for _, k, _ in SIM.log))]


def s_render_fails():
    start = local("2026-09-25 13:00")
    fr = frame(start, "midday")
    orig, boom = fr.render, [start + 300]

    def render(now, fetched_at, note=None):
        if boom and now >= boom[0]:
            boom.pop()
            raise RuntimeError("a render that fails, on purpose")
        return orig(now, fetched_at, note)
    fr.render = render
    # The loop prints the traceback it caught; this one is expected
    with open(os.devnull, "w") as quiet:
        stderr, sys.stderr = sys.stderr, quiet
        try:
            run(fr, start, 20)
        finally:
            sys.stderr = stderr
    bad = [kw for t, k, kw in SIM.log if k == "draw" and abs(t - (start + 300)) < 2]
    return [("a failed render logs shown=0 and the loop goes on",
             bool(bad) and bad[0]["shown"] == 0 and len(SIM.renders) >= 18)]


def s_no_hooks():
    """The planes frame has no screen_key or mood: plugged in, it redraws every minute."""
    start = local("2026-09-25 13:00")
    inner = frame(start, "midday")

    class Plain:
        log, fetch_log = {}, {}

        def configure(self, args):
            return inner.configure(args)

        def fetch(self, session, now):
            pass

        def fetch_every(self, now):
            return 300

        def render(self, now, fetched_at):
            return inner.render(now, fetched_at)

        def moving(self, now):
            return False

        def in_night(self, now):
            return False

        def next_morning(self, now):
            return now + 3600

        def night_key(self, now, mode):
            return mode

        def render_night(self, now, mode):
            return inner.render(now, 0)
    run(Plain(), start, 20)
    return [("a frame without the hooks shows every minute plugged in", len(SIM.shows) >= 19)]


SCENARIOS = {"flight": s_flight, "battery": s_battery, "near-landing": s_near_landing,
             "mid-fall": s_mid_fall, "mid-fall-vel": lambda: s_mid_fall(vel_v=True), "lost": s_lost,
             "unplug-mid-pass": s_unplug_mid_pass, "clock-back": s_clock_back,
             "night-mid-live": s_night_mid_live, "render-fails": s_render_fails, "no-hooks": s_no_hooks}


def main():
    global SIM
    verbose = "-v" in sys.argv
    names = [a for a in sys.argv[1:] if a != "-v"] or list(SCENARIOS)
    install_fakes()
    failed = 0
    for name in names:
        SIM = Sim()
        sky._kept.clear()
        checks = SCENARIOS[name]()
        print("%s: %d renders, %d screen updates, %d flashes" % (name, len(SIM.renders), len(SIM.shows), len(flashes())))
        if verbose:
            shown = dict(SIM.shows)
            for r in SIM.renders:
                if r["t"] in shown and r["mood"] != "live":
                    print("    %-9s %-5s %-5s %-22s %s" % (hhmm(r["t"]), r["mood"], "FLASH" if shown[r["t"]] else "show",
                                                         r["head"], r["foot"] or ""))
        for check, ok in checks:
            print("  %s %s" % ("ok  " if ok else "FAIL", check))
            failed += not ok
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
