# kindle-planes — agent context

Facts you can't get by reading the code. Everything else is in the README and `docs/`.

Everything runs on the Kindle. The laptop only previews, builds and deploys.

## Preview, don't fetch

Render from samples, never from the live API on the laptop: a laptop on the same network as
a Kindle shares its public IP and trips adsb.lol's rate limit for both. The same goes for
the sky frame's CelesTrak orbits, which CelesTrak rate-limits per IP: only the device
fetches them, at most once every 20 hours, and keeps them in `orbits.csv`.

```bash
uv run --python 3.9 --with pillow==9.0.1 --with requests python planes/planes.py \
  --sample planes/samples/crowded.json --rotate 0 --out out/x.png
```

Every style, every sample, one image: `planes/samples/sheet.py STYLE out/sheet.png` (add
`--night` yourself for `night.json`; the sheet does). As a PW2 sees it: add
`--panel 758x1024 --config planes/config-pw2.json`. Regenerate samples after changing the
home location: `planes/samples/make.py` and `make_night.py`.

The sky frame: `planes/sky.py --sample planes/samples/sky/night.json --rotate 0 --out
out/x.png` (same `uv run` prefix, same `--panel` and `--config`), or `sheet.py sky`. Each
sample carries its own time and orbits, so it renders the same whatever the date.

The pinned Python 3.9 + Pillow 9 preview is the compatibility floor. Keep `planes.py` 3.9
compatible, and everything else in `planes/` with it. The Kindle itself runs a standalone
Python 3.12 with a Pillow built against its own FreeType (`docs/device-setup.md`).

## Kindle quirks

- Pillow `stroke_width` segfaults the Kindle's FreeType. Use `halo_text()`.
- The screen's controller does its own 16-level quantizing. Don't posterize.
- The SoC's SNVS RTC wakes a PW4 from suspend, not the PMIC's. `power.py` finds it by
  name: `rtc1` on a PW4, `rtc2` on a PW2. Never suspend without an alarm armed.
- A Kindle plugged into a computer wakes from suspend at once and drops into Drive Mode,
  which takes `/mnt/us` away from the device. Test suspend on battery or a wall charger,
  and never let a write to `/mnt/us` crash the loop (`write_json()`).
- FBInk returns before the panel finishes. `fbink -w`, or the next suspend can hang the kernel.

## Two models

The PW4 is the main one: what the photos show, what the frame fits. A Paperwhite 2 (2013)
also runs it, tested one night on 2026-09-30, and differs in ways the code can't see:

- 758x1024 panel. Everything is still drawn on the PW4's 1448x1072 canvas and scaled at
  output (`turn()`), so `safe` and every layout number mean the same on both.
- Firmware tops out at 5.12, soft-float, on a 3.0 kernel. It needs its own Python bundle,
  built from source (`build/python-softfloat.sh`), and its own SSH
  (`build/dropbear.sh`, `build/install-ssh-dropbear.sh`); `tools/install.sh` picks the
  bundle by itself.
- MAX77696 power chip: battery, charger, light and power key have other names, found by
  pattern in `power.py`.
- Suspend works there too (tested on battery 2026-09-30): the SNVS RTC (`rtc2`) wakes it,
  and it averages about 10 mA like a framed PW4. The power button's hold and exit work.
- Its config uses `"panel_w": 560`: the wider story panel keeps long city names on one line.

`safe` is the visible area, measured right at the mat, and the map runs to it. Text (story
panel, the featured plane's label, the night caption) keeps `inset` further in: 12 px, 1 mm
on either model. The PW4's config has `"inset": 0` because its hand-set `safe` predates the
rule and already has its margin; its frames are pixel-identical either way.

## Deploying

- `tools/install.sh` is the first install: Python bundle, a `config.json` if there is none
  (`planes/config-pw2.json` on a 758x1024 panel), the boot job, then `deploy.sh`. After
  that, only `deploy.sh`.
- Every tool takes `KINDLE=host` (default `kindle`), so a second Kindle is `KINDLE=kindle2`.
- `tools/deploy.sh` copies `planes/` to `/mnt/us/planes` and restarts the loop. It waits for
  the Kindle's Wi-Fi window (up for a few seconds every 5 minutes in power-save mode). One
  press of the power button opens a 10-minute window immediately.
- `config.json` is never deployed. The device keeps its own; edit it over SSH.
- `tools/deploy.sh --hold` leaves the Kindle awake with Wi-Fi on. Remove
  `/mnt/us/planes/HOLD` when done, or the battery drains.
- Runtime files stay on the device and are gitignored: `cache.json`, `traffic.json`,
  `tracks.json`, `power.log`, and the sky frame's `orbits.csv` and `balloon.json`.
- `tools/gift.sh letter.txt` leaves a letter (`gift.txt`) on the sky frame until the first
  press of the power button, which renames it `gift.seen` and writes that day to
  `gift.date`; it comes back on that date every year. Deploys never carry any of them. It
  also copies the letter into `/mnt/us/documents` as a book.
- `"frame"` in the device's `config.json` picks `planes` or `sky`; `run.sh frame NAME` or
  `tools/deploy.sh --frame NAME` switches and restarts. Both frames always ship.
- `tools/grid.sh` shows the test pattern for measuring `safe` and stops the loop to do it.
  Always finish with `tools/grid.sh done`, or the Kindle stays awake on the pattern.
- After a visual change, show a screenshot: `tools/fbshot.sh` reads the framebuffer.
- Measure power only on battery: `ac=0` rows in `power.log`, summarized by `tools/battery.py`.

## Two frames, one loop

`loop.py` owns everything that was hard won on the device: Wi-Fi joins and recovery,
backoff, suspend, the frontlight, the power button, night and low-battery rest. A frame
(`planes.py`, `sky.py`) only fetches and draws; its hooks are listed at the top of
`loop.py`. Change device behavior there, once, not in a frame. `sky.py` borrows fonts,
layout and helpers from `planes.py` (`import planes as P`), so `load_config` and
`apply_layout` serve both.

The sky frame's headline is chosen by `hero()` in `sky.py`: events with a wonder score,
explained in `docs/sky.md`. Add a new kind of thing as an event there, never as a special
case. It never shows bad news: say what to look forward to instead.

Design it on the panel, through the webcam (`tools/camshot.sh`) as well as `fbshot.sh`:
e-ink black is a dark gray, so grays below about 150 vanish, and anything under 34 px is
unreadable from across a room.

After changing `loop.py` or when the sky frame redraws, run `tools/simulate.py`: the real
loop and frame on a fake clock, panel and SondeHub, through a balloon flight, passes,
unplugging, a clock set back and a failed render, with checks on every screen update and
flash. Nothing touches the network or a Kindle.

The sky frame's pure-Python work (sgp4 pass searches, rise and set times, the star field)
is cached between frames by `kept()`; the first frame after a start costs the most.
`planes/vendor/sgp4` is upstream sgp4 2.27 (its pure-Python modules and `omm.py`),
unmodified and excluded from ruff: to update it, copy a release's `sgp4/*.py` over it.
Orbits come as CelesTrak's CSV, not TLEs: TLEs stop at catalog number 99999, and every
launch since mid-2026 is past it.

## Style rules

- Comments say why, not what. Delete code instead of commenting it out.
- Words on the screen are plain, for anyone in the kitchen: "Jupiter at its brightest",
  never "opposition"; "Half moon", not "first quarter"; "Hobby balloon", not "pico".
- `ruff check planes tools insert` must pass (`ruff.toml`).
- Styles: `bold-right` is the default and what the photos show. `bold` mirrors it,
  `bold-traffic` adds the day's chart, `detailed` is the dense original.
