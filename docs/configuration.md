# Configuration

All settings live in `/mnt/us/planes/config.json` on the Kindle. Edit it over SSH:

```bash
ssh kindle vi /mnt/us/planes/config.json
```

The Kindle rereads it every minute, so there's nothing to restart. A deploy never
overwrites it. If the file has a typo, the Kindle keeps using the last version that worked
and logs the error in `/tmp/planes.log`.

## Settings

| Key | What it does | Default |
|---|---|---|
| `lat`, `lon` | Your home. The map is centered here | Toronto City Hall |
| `city` | The name shown for your end of a route, as in "Hong Kong → Toronto" | `"Toronto"` |
| `airports` | Airports to mark on the map, as `[["YYZ", lat, lon], ...]` | YYZ and YTZ |
| `style` | `bold-right`, `bold` (mirrored), `bold-traffic` (adds today's chart) or `detailed` (smaller text, more labels) | `bold-right` |
| `heading` | The compass direction you face when looking at the frame. The map turns so it points up | `0` (north up) |
| `rotate` | How the Kindle sits in the frame: `270` with its logo on the left, `90` on the right | `270` |
| `safe` | The part of the screen the frame's mat leaves visible, as `[left, top, right, bottom]` in pixels. See [frame.md](frame.md) | Fits the 13×18 insert |
| `inset` | How far text stays inside `safe`, in pixels. 12 is 1 mm | `12` |
| `panel_w` | Width of the text panel in pixels. The Paperwhite 2 config uses `560` | Set by the style |
| `night` | When to show the night view | `["23:00", "07:00"]` |
| `tz` | Your time zone in POSIX form, e.g. `"PST8PDT,M3.2.0,M11.1.0"` | Toronto |
| `frontlight` | Front light level from 0 to 24, used only while charging | `3` |
| `power` | `wifi_toggle`, `suspend` and `governor`. Leave them on for battery life | All on |

## A new home

Set `lat`, `lon`, `city` and `airports`, then redraw the lake for your area:

```bash
uv run python tools/shore.py "Lake Ontario" 43.65 -79.38
tools/deploy.sh
```

`shore.py` takes the lake's name as Natural Earth spells it. If there's no lake nearby,
set `planes/shore.json` to an empty list, `[]`.

## The power button

- **One press** wakes the Kindle with Wi-Fi on for 10 minutes, so you can reach it over SSH.
- **A second press** a few seconds later hands the screen back to the normal Kindle
  interface. The display comes back on the next reboot.

## Two Kindles in one home

Kindles on the same network share a public IP, and with it adsb.lol's rate limit. Two
Kindles fetching every 5 to 10 minutes stay well within it. Don't fetch live data from a
computer on the same network; preview from the samples instead.
