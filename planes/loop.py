"""The screen loop every frame shares: wake, fetch over Wi-Fi when due, draw, push to the
e-ink panel, sleep, and the night and low-battery rest. A frame (planes.py, sky.py)
supplies the data and the pictures; this owns timing, power and Wi-Fi recovery, which
were hard won on the device (docs/power.md).

A frame is an object with:
    configure(args)          re-read config.json (every loop, so edits apply live) and return
                             the settings this needs: power, rotate, style, frontlight
    fetch(session, now)      pull its data; raise requests.RequestException or ValueError
                             when the fetch as a whole failed
    fetch_every(now)         seconds until the next fetch after a good one
    render(now, fetched_at)  the picture, on the landscape canvas (fetched_at 0 = never)
    moving(now)              True while the picture changes minute to minute; otherwise
                             the loop sleeps until the next fetch
    in_night(now), next_morning(now)
                             the quiet hours, when nothing is fetched
    night_key(now, mode)     redraw the rest picture whenever this changes
    render_night(now, mode)  that picture; mode is "night", or "low" on a dying battery
and `fetch_log` and `log`, dicts of fields for the power log's fetch and draw lines.
Optionally `idle_redraw_s`: the longest a still picture waits for a redraw when the next
fetch is further off than that (the sky turns even when nothing needs fetching), and
`pressed()`: True when the frame takes a power-button press for itself (the sky frame's
gift opening), which then redraws at once instead of holding awake. The loop
sets `plugged` on the frame each round, so it can fetch faster on a charger. Optionally
`next_due(now)`: when its next fetch falls due, so the morning after the quiet hours
waits for it rather than joining Wi-Fi with nothing to fetch (the sky frame computes
most of what it shows; planes always has something to fetch by morning).

Plugged in, battery doesn't matter: Wi-Fi stays up (SSH works without the power button),
the Kindle never suspends, and the picture redraws every minute. Anything on a shared rate
limit keeps its pace; that's up to the frame's fetch_every.

A frame can make that calmer with two optional hooks:
    screen_key()  what the last render says, as a value; the first item the moment (the
                  headline, say), a change of which is worth a full flash
    mood(now)     "calm", "soon" (something good within the half hour) or "live"
Then, plugged in, it still checks every minute but the screen only changes when what it
says does, or every 15 minutes as the sky turns; while it's "live", every 15 seconds. A full
flash only on a new headline, when something starts or ends, or once enough partial updates
leave ghosts.
"""

import os
import re
import subprocess
import sys
import time
import traceback

import power
import requests
from PIL import Image

DRAW_S = 60
FULL_REFRESH_S = 1800     # a full e-ink flash this often to clear ghosting
NIGHT_WAKE_S = 1800       # brief wakes at night so no single suspend runs for hours
MAX_BACKOFF_S = 600       # adsb.lol rate-limits; failures back off to this
LIVE_S = 15               # plugged in, the redraw while something crosses the sky
CALM_REDRAW_S = 900       # plugged in, the longest a still screen goes without a redraw
GHOST_PARTIALS = 40       # partial updates before a full flash clears the ghosting
LOW_BATTERY = 5
LOW_BATTERY_RESUME = 10
UA = {"User-Agent": "kindle-planes/0.1 (home display)"}

FBINK = None
for cand in ("/mnt/us/libkh/bin/fbink", "/var/local/kmc/bin/fbink", "/mnt/us/usbnet/bin/fbink", "fbink"):
    if cand == "fbink" or os.path.exists(cand):
        FBINK = cand
        break


def panel_size():
    """The panel's native portrait size. Everything is drawn on the PW4's 1448x1072 canvas;
    a smaller panel (a PW2's 758x1024 is the same shape) gets the frame scaled to fit."""
    try:
        with open("/sys/class/graphics/fb0/modes") as f:
            m = re.match(r"\w+:(\d+)x(\d+)", f.read())  # "U:758x1024p-0"
        if m:
            return int(m.group(1)), int(m.group(2))
    except OSError:
        pass
    return 1072, 1448


PANEL = panel_size()


def turn(img, rotate):
    """Scale to the panel if it's smaller than the canvas, then clockwise quarter turns onto
    it. transpose() is a lossless row copy; rotate() resamples every pixel and cost the
    Kindle a few hundred ms a frame."""
    size = (PANEL[1], PANEL[0]) if img.size[0] > img.size[1] else PANEL
    if img.size != size:
        # BILINEAR: 370 ms on a PW2 where LANCZOS took 830, and at this 0.7x scale the two
        # are indistinguishable even magnified (Pillow widens either filter to the area)
        img = img.resize(size, Image.BILINEAR)
    if not rotate % 360:
        return img
    return img.transpose({90: Image.ROTATE_270, 180: Image.ROTATE_180, 270: Image.ROTATE_90}[rotate % 360])


def show(path, flash):
    # -w: block until the panel finishes refreshing. Suspending the EPDC mid-update hung
    # the kernel roughly every 7th sleep, and the watchdog rebooted the Kindle each time
    args = [FBINK, "-q", "-w", "-g", "file=%s" % path]
    if flash:
        args.insert(2, "-f")
    subprocess.call(args)


def battery_low(was_low):
    bat = power.battery()
    if not bat or not bat[0]:
        return False
    cap, on_ac = int(bat[0]), bat[3] == "1"
    if on_ac:
        return False
    return cap <= (LOW_BATTERY_RESUME if was_low else LOW_BATTERY)


def set_hold(on):
    """The HOLD file keeps the Kindle awake with Wi-Fi up. It lives in /mnt/us, which a
    computer's USB takes away (Drive Mode), so a failed write is skipped, never fatal."""
    try:
        if on:
            open(power.HOLD, "w").close()
        elif os.path.exists(power.HOLD):
            os.remove(power.HOLD)
    except OSError:
        pass


def frame_took(frame):
    return bool(getattr(frame, "pressed", None) and frame.pressed())


def run(frame, args):
    cfg = frame.configure(args)
    power.set_governor(cfg["power"].get("governor"))
    session = requests.Session()
    session.headers.update(UA)
    # PGM: uncompressed, 7 ms to write on the Kindle where PNG took 500+
    frame_path = args.out or "/tmp/planes.pgm"
    night_drawn = ""
    low = False
    started, hold_until, hold_started = time.time(), 0, 0
    fetched_at = next_fetch = last_full = 0.0
    failures = 0
    last_style = cfg["style"]
    was_plugged = False
    shown_key, shown_mood, shown_at, partials = None, None, 0.0, 0
    while True:
        cfg = frame.configure(args)
        pw = cfg["power"]
        restyled, last_style = last_style != cfg["style"], cfg["style"]
        now = time.time()
        plugged = frame.plugged = power.on_ac()
        if pw.get("wifi_toggle") and (plugged or plugged != was_plugged):
            # On a charger: Wi-Fi up and kept up (brought back if it drops). Off it: back to
            # Wi-Fi only for fetches
            if plugged:
                power.wifi_up()
            else:
                power.wifi_down()
        was_plugged = plugged
        # A power-button hold ends after its 10 minutes, or as soon as HOLD is gone, here at
        # the top so it also ends at night; Wi-Fi goes down with it, never left up into suspend
        if hold_until and (time.time() > hold_until or not os.path.exists(power.HOLD)):
            set_hold(False)
            hold_until = 0
            if pw.get("wifi_toggle") and not plugged:
                power.wifi_down()

        low = not args.once and battery_low(low)
        if not args.once and (frame.in_night(now) or low):
            power.set_frontlight(0)  # nobody's reading it at night or on a dying battery
            mode = "low" if low else "night"
            if night_drawn != frame.night_key(now, mode):
                try:
                    img = frame.render_night(now, mode)
                    turn(img, cfg["rotate"]).save(frame_path)
                    show(frame_path, flash=True)
                    night_drawn = frame.night_key(now, mode)
                    power.log("night_draw", mode=mode, **frame.log)
                except Exception:
                    traceback.print_exc()
            if pw.get("wifi_toggle") and not plugged:
                power.wifi_down()
            suspend = pw.get("suspend", False) and time.time() - started > 60 and not plugged
            # On a charger, look again every minute, so unplugging is noticed
            until = now + NIGHT_WAKE_S if low else min(now + NIGHT_WAKE_S, frame.next_morning(now))
            woke = power.sleep_until(min(until, now + 60) if plugged else until, suspend=suspend)
            power.log("wake", how=woke, night=1)
            if woke == "button" and frame_took(frame):
                night_drawn = ""
            # Fetch straight away when morning comes, if there's anything to fetch
            next_fetch = frame.next_due(now) if hasattr(frame, "next_due") else 0
            last_full = 0
            continue

        if now >= next_fetch:
            woke = time.time()
            # Escalate on a dead link (wifid can lose the network overnight and never retry):
            # radio cycle every 3rd failure, restart wifid after ~1 h, reboot after ~3 h
            if failures and failures % 36 == 0:
                power.reboot()
            if failures and failures % 12 == 0:
                power.restart_wifid()
            took = power.wifi_up(reset=failures >= 3 and failures % 3 == 0) if pw.get("wifi_toggle") else 0.0
            odd = False
            try:
                # wifid reports CONNECTED a moment before the link carries traffic; retry
                # inside this wake rather than paying for another Wi-Fi join next minute
                for attempt in range(3):
                    try:
                        frame.fetch(session, now)
                        break
                    except requests.ConnectionError:
                        if attempt == 2:
                            raise
                        time.sleep(2)
                fetched_at, failures = now, 0
            except (requests.RequestException, ValueError) as e:
                failures += 1
                print("fetch failed (%d): %r" % (failures, e), file=sys.stderr, flush=True)
            except Exception:
                # A server answered with something nobody expected: a bad answer, not a dead
                # link, so no Wi-Fi recovery, and try again in a while rather than at once
                odd = True
                traceback.print_exc()
            if pw.get("wifi_toggle") and not plugged:
                power.wifi_down()
            if odd:
                next_fetch = now + 900
            elif failures:
                next_fetch = now + min(60 * failures, MAX_BACKOFF_S)
            else:
                next_fetch = now + frame.fetch_every(now)
            power.log("fetch", ok=int(not failures and not odd), wifi_s="%.1f" % (took or -1),
                      awake_s="%.1f" % (time.time() - woke), **frame.fetch_log)

        # Suspend switches the frontlight off, so a steady glow is only possible awake:
        # light it when on a charger (and skip suspend below), keep it dark on battery
        power.set_frontlight(cfg["frontlight"] if plugged else 0)
        drawn = time.time()
        calm = plugged and hasattr(frame, "screen_key")
        mood = None
        shown = 1
        try:
            img = frame.render(drawn, fetched_at)
            if calm:
                key, mood = frame.screen_key(), frame.mood(drawn)
                # (Not "since" alone: a clock set back must not stall the redraw)
                shown = int(restyled or key != shown_key or mood != shown_mood or mood == "live"
                            or not 0 <= drawn - shown_at < CALM_REDRAW_S)
            if shown:
                turn(img, cfg["rotate"]).save(frame_path)
            if shown and not args.out:
                if calm:
                    # One clean flash for a new moment, for something starting to happen and for
                    # the quiet after it (not between soon and live: trains come in waves)
                    # Ghosts wait out the action (up to half an hour): its end flashes anyway
                    flash = restyled or not shown_key or key[0] != shown_key[0] \
                        or partials >= GHOST_PARTIALS * (3 if mood == "live" else 1) \
                        or (mood != shown_mood and "calm" in (mood, shown_mood))
                    shown_key, shown_mood, shown_at = key, mood, drawn
                else:
                    flash = restyled or drawn - last_full > FULL_REFRESH_S
                show(frame_path, flash=flash)
                partials = 0 if flash else partials + 1
                if flash:
                    last_full = drawn
        except Exception:
            if args.once:
                raise
            traceback.print_exc()
            shown = 0
        power.log("draw", ms=int((time.time() - drawn) * 1000), shown=shown, **frame.log)
        if args.once:
            print(frame_path)
            return

        # Draw on the minute so the clock is exact; with nothing to move, just wait for the fetch.
        # Plugged in and live, every 15 seconds
        step = LIVE_S if mood == "live" else DRAW_S
        next_draw = (int(time.time() // step) + 1) * step if plugged or frame.moving(drawn) else next_fetch
        if getattr(frame, "idle_redraw_s", None):
            next_draw = min(next_draw, drawn + frame.idle_redraw_s)
        # Never deep-sleep in the first minute after start, so a bad build can be stopped over SSH
        suspend = pw.get("suspend", False) and time.time() - started > 60 and not plugged
        woke = power.sleep_until(min(next_draw, next_fetch), suspend=suspend)
        if woke == "button" and frame_took(frame):
            last_full = 0  # a new picture altogether: flash it in clean
            power.log("wake", how="button_frame")
            continue
        if woke == "button" and hold_until and time.time() - hold_started > 5:
            # A second press while held means leave: hand the screen back to the Kindle
            # UI until the next reboot. The gap keeps a quick double tap from exiting.
            power.log("button_exit")
            set_hold(False)
            subprocess.call(["sh", os.path.join(os.path.dirname(os.path.abspath(__file__)), "run.sh"), "stop"])
            return
        if woke == "button":
            # A power-button press means someone wants in: hold awake with Wi-Fi for 10 minutes
            set_hold(True)
            hold_started = time.time()
            hold_until = hold_started + 600
            power.wifi_up()
            power.log("button_hold")
        power.log("wake", how=woke)
