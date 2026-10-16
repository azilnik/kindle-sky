# Kindle Sky: agent guide

A jailbroken Kindle in a picture frame draws the sky above home. Everything runs on the
Kindle; the laptop only previews, builds and deploys. This file is what you can't get from
reading the code, plus playbooks for what people ask. The README and `docs/` are for humans.

## Map

| Path | What |
|---|---|
| `sky/sky.py` | The frame: fetches orbits and balloons, picks the headline (`hero()`), draws the dome and panel. Its `Frame` class is what the loop runs |
| `sky/loop.py` | The screen loop: Wi-Fi, fetch timing, suspend, power button, night, low battery. Device behavior lives here, never in `sky.py` |
| `sky/base.py` | `config.json`, the visible area, fonts, text fitting, home geometry |
| `sky/astro.py` | Sun, Moon, planets, eclipses, almanac. Pure math, no network |
| `sky/power.py` | Kindle hardware: Wi-Fi, RTC suspend, battery, frontlight, SSH restart, `power.log` |
| `sky/run.sh`, `sky/sky.conf` | Supervisor and upstart boot job, on the device |
| `sky/config.json`, `config-pw2.json` | First configs for each model; the device keeps its own copy |
| `sky/samples/*.json` | Frozen sky data with its own timestamp, for previews |
| `tools/` | `install.sh`, `deploy.sh`, `check.sh`, `simulate.py`, `gift.sh`, `grid.sh`, `fbshot.sh`, `battery.py` |
| `insert/` | 3D-printed parts (manifold3d scripts and their meshes); `docs/frame.md` says what to print |
| `build/` | How the Kindle's Python bundles are built (Docker, hours; rarely needed) |

## Before you commit

`tools/check.sh` must pass: ruff, the loop simulator, every sample rendered on both models,
the gift letter. Then look at `out/sheet.png` (and `out/sheet-pw2.png`) yourself, and show
the person a screenshot after any visual change: rendered, or from the device with
`tools/fbshot.sh`.

Keep everything in `sky/` Python 3.9 compatible with Pillow 9: that pinned preview is the
compatibility floor. The Kindle runs a standalone Python 3.12 with its own Pillow.

## Never

- **Never fetch live data from the laptop.** It shares the Kindle's public IP and CelesTrak
  rate-limits per IP; only the device fetches orbits, once every 20 hours at most. Preview
  from `sky/samples/`.
- **Never deploy `config.json`.** `deploy.sh` excludes it; the device's copy is the truth.
  Edit it over SSH.
- **Never suspend without an RTC alarm armed**, and never test suspend while the Kindle is
  plugged into a computer (see quirks).
- **Never leave `HOLD` behind** (`tools/deploy.sh --hold`, `tools/grid.sh`): the Kindle
  stays awake and drains in a day. Finish with `rm /mnt/us/sky/HOLD` or `tools/grid.sh done`.
- **Never use Pillow's `stroke_width`**: it segfaults the Kindle's FreeType. `glow_text()`.
- **Never posterize**: the panel's controller does its own 16-level quantizing.

## Playbooks

Every tool takes `KINDLE=host` (default `kindle`, the `~/.ssh/config` name). The Kindle's
Wi-Fi is up only a few seconds every 5 minutes on battery: `deploy.sh` waits for that
window, and one press of the power button opens a 10-minute one. If SSH times out, ask the
person to press it once; don't press for them by any other means.

**Install on a new Kindle.** It must already answer `ssh <host>` (jailbreak and SSH are
manual: `docs/device-setup.md`). Ask where home is if you don't know; turn a city or address
into latitude and longitude yourself. Then:
`KINDLE=<host> tools/install.sh --home LAT,LON`. It detects PW4 or PW2 from the panel and
firmware, picks the Python bundle and config, and migrates an old `/mnt/us/planes` install.
Then set `tz` (POSIX form, the Kindle has no zoneinfo) and ask which way the frame faces
for `heading`.

**Change a setting.** Read the file, change the key, write it back:
`ssh kindle cat /mnt/us/sky/config.json`, then `ssh kindle 'cat > /mnt/us/sky/config.json'`
with the new JSON on stdin. Validate the JSON first. It applies within a minute, no restart.
Keys: `docs/configuration.md`.

**Ship a code change.** `tools/check.sh`, then `tools/deploy.sh`, then `tools/fbshot.sh`
and look at the result. `deploy.sh` restarts the loop; the first minute after a start never
suspends, so a bad build can be stopped over SSH (`ssh kindle sh /mnt/us/sky/run.sh stop`).

**"It stopped updating."** In order: `ssh kindle tail -50 /tmp/sky.log` (crashes, restarts);
`ssh kindle tail -30 /mnt/us/sky/power.log` (events: `fetch ok=0` is the network,
`suspend_refused` the kernel, `reboot` the loop giving up); `ssh kindle cat /tmp/sky.pid`
and whether it's alive. A stale picture with "Battery low" is the low-battery rest.
`run.sh restart` restarts it. Don't reboot without asking.

**Measure the visible area.** `tools/grid.sh` (stops the loop, shows a grid); the person
reads the edges off it; write `safe`; `tools/grid.sh check` draws the box; always end with
`tools/grid.sh done`.

**Give it as a gift.** `tools/gift.sh letter.txt`: renders to `out/gift.png` first (show
it), refuses a letter too long for one screen, then deploys and leaves it up until the
first press. Comes back every year on the day it was opened.

**Battery life.** Only `ac=0` rows count; `scp kindle:/mnt/us/sky/power.log .` then
`tools/battery.py power.log`. Expect ~4.7 mA on a PW4, ~10 mA on a PW2.

**Print parts.** `docs/frame.md` has the table per Kindle. Scripts regenerate meshes
(command at the top of each); every committed mesh is reproducible byte for byte.

## Kindle quirks

- The SoC's SNVS RTC wakes a Kindle from suspend, not the power chip's. `power.py` finds it
  by name: `rtc1` on a PW4, `rtc2` on a PW2.
- A Kindle plugged into a computer wakes from suspend at once and drops into Drive Mode,
  which takes `/mnt/us` away from the device. Test suspend on battery or a wall charger,
  and never let a write to `/mnt/us` crash the loop (`base.write_json()`).
- FBInk returns before the panel finishes. `fbink -w`, or the next suspend can hang the kernel.
- `wifid` reports connected a moment before the link carries traffic; the loop retries in
  the same wake.

## Two models

The PW4 (2018) is the main one. A Paperwhite 2 (2013) runs the same code and differs in ways
the code can't see:

- 758x1024 panel. Everything is drawn on the PW4's 1448x1072 canvas and scaled at output
  (`loop.turn()`), so `safe` and every layout number mean the same on both.
- Firmware tops out at 5.12, soft-float, on a 3.0 kernel: its own Python bundle
  (`build/python-softfloat.sh`) and its own SSH (`build/dropbear.sh`). `install.sh` picks
  the bundle by itself.
- MAX77696 power chip: battery, charger, light and power key have other names, found by
  pattern in `power.py`. Its charger's `online` sticks at 1 after unplugging; `on_ac()`
  trusts the USB controller's `vbvolt` instead. Before blaming a charger, ask whether it's
  actually plugged in.
- Its config uses `"panel_w": 560`.

`safe` is the visible area, measured right at the mat; lettering keeps `inset` (12 px, 1 mm
on either model) further in.

## How the sky frame thinks

The headline is chosen by `hero()`: every candidate is an event with a time window and a
wonder score, explained in `docs/sky.md`. Add a new kind of thing as an event there, never
as a special case. It never shows bad news: say what to look forward to instead.

After changing `loop.py` or when the frame redraws, run `tools/simulate.py` (part of
`check.sh`): the real loop and frame on a fake clock, panel and SondeHub, with checks on
every screen update and flash.

Pure-Python work (sgp4 pass searches, rise and set times, the star field) is cached
between redraws by `kept()`; the first redraw after a start costs the most.
`sky/vendor/sgp4` is upstream sgp4 2.27, unmodified and excluded from ruff: to update it,
copy a release's `sgp4/*.py` over it. Orbits come as CelesTrak's CSV, not TLEs: TLEs stop
at catalog number 99999, and every launch since mid-2026 is past it.

Design on the panel, not just the laptop: e-ink black is a dark gray, so grays below about
150 vanish, and anything under 34 px is unreadable from across a room.

## Style

- Comments say why, not what. Delete code instead of commenting it out.
- Words on the screen are plain, for anyone in the kitchen: "Jupiter at its brightest",
  never "opposition"; "Half moon", not "first quarter"; "Hobby balloon", not "pico".
- No 24-hour times on screen.
