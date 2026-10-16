# Configuration

All settings live in `/mnt/us/sky/config.json` on the Kindle. Edit it over SSH:

```bash
ssh kindle vi /mnt/us/sky/config.json
```

The Kindle rereads it every minute, so there's nothing to restart. A deploy never
overwrites it. If the file has a typo, the Kindle keeps using the last version that worked
and logs the error in `/tmp/sky.log`.

`tools/install.sh` writes the first one: [sky/config.json](../sky/config.json) on a
Paperwhite 4, [sky/config-pw2.json](../sky/config-pw2.json) on a Paperwhite 2, with your
home from `--home LAT,LON`.

## Settings

| Key | What it does | Default |
|---|---|---|
| `lat`, `lon` | Your home, in degrees. Everything is seen from here | Toronto City Hall |
| `heading` | The compass direction you face when looking at the frame. The dome turns so it's at the top, like a map | `0` (north up) |
| `tz` | Your time zone in POSIX form, e.g. `"PST8PDT,M3.2.0,M11.1.0"` for Vancouver, `"GMT0BST,M3.5.0/1,M10.5.0"` for London. The Kindle has no time zone names to look up | Toronto |
| `sky_glow` | How dark your sky is, for meteor shower rates: `dark`, `rural`, `suburb`, `city` or `downtown` | `"city"` |
| `rotate` | How the Kindle sits in the frame: `270` with its logo on the left, `90` on the right | `270` |
| `safe` | The part of the screen the frame's mat leaves visible, as `[left, top, right, bottom]` in pixels. See [frame.md](frame.md) | Fits the 13×18 insert |
| `inset` | How far text stays inside `safe`, in pixels. 12 is 1 mm | `12` |
| `panel_side` | Which side the text panel is on: `left` or `right` | `"left"` |
| `panel_w` | Width of the text panel in pixels. The Paperwhite 2 config uses `560` | `500` |
| `night` | Quiet hours with no fetching; the sky redraws every half hour | `["23:00", "07:00"]` |
| `frontlight` | Front light level from 0 to 24, used only while charging | `3` |
| `power` | `wifi_toggle`, `suspend` and `governor`. Leave them on for battery life. On a charger they step aside: Wi-Fi stays up and the Kindle stays awake, checking every minute but changing the screen only when what it says changes, and every 15 seconds while something crosses the sky | All on |

Weather balloons are any SondeHub hears within 250 km of home, so there's nothing to set for
them. A few launch sites around the Great Lakes are named on screen (*from Buffalo*); anywhere
else a balloon's start reads as a distance and direction (*from 120 km SW*).

## The power button

- **One press** wakes the Kindle with Wi-Fi on for 10 minutes, so you can reach it over SSH.
  While a gift letter is up, the first press opens the sky instead
  ([sky.md](sky.md#give-it-as-a-gift)).
- **A second press** a few seconds later hands the screen back to the normal Kindle
  interface, with its library and books. The display comes back on the next reboot.

## Two Kindles in one home

They work side by side. CelesTrak limits orbit downloads per public IP, and each Kindle
fetches them at most once every 20 hours, so two stay well within it. Don't fetch live data
from a computer on the same network; preview from the samples instead (`tools/check.sh`).
