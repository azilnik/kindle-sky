# Device setup

Built for the Kindle Paperwhite 10th generation (2018, "PW4"), 1072×1448 screen. A
Paperwhite 2 (2013) also runs it; its differences are at the [end](#paperwhite-2). Other
Kindles need work: sleep, wake and the front light are all device-specific.

This is what was done once, in order. Each step is manual; the jailbreak can't be scripted
and Amazon patches it, so block firmware updates as soon as it's in.

## 1. Jailbreak

Follow [kindlemodding.org](https://kindlemodding.org/jailbreaking/). On firmware 5.16.3 to
5.19.5, SpiderCat works entirely on the device: open the Kindle's browser, download the
book, open it. Do not update the firmware afterwards.

## 2. SSH over Wi-Fi

`build/install-ssh.sh` is a KUAL scriptlet. Put it in `documents/` with a folder
`/mnt/us/claude-bootstrap/` holding `unl.tar` (notmarek's USBNetLite) and your public key
as `authorized_keys`. Opening the scriptlet installs dropbear, key-only login, root, and
starts it at boot. It writes the Kindle's IP to `claude-bootstrap/ip.txt`.

On your computer, add a host to `~/.ssh/config`:

```
Host kindle
  HostName <the IP>
  User root
  IdentityFile ~/.ssh/kindle
```

Everything in `tools/` uses `ssh kindle`. Set `KINDLE=othername` to use another host.

## 3. FBInk

`loop.py` looks for `fbink` at `/mnt/us/libkh/bin`, `/var/local/kmc/bin` and
`/mnt/us/usbnet/bin`. It comes with the KindleModding tool packages and with KOReader.

## 4. Install

Press the power button once so the Kindle stays on Wi-Fi, then, with your home's latitude
and longitude:

```bash
tools/install.sh --home 43.65,-79.38
```

It's safe to run again. It reads the panel to tell a Paperwhite 4 from a Paperwhite 2, and
the firmware to pick the right Python, then does four things:

1. **Python.** Downloads `kindle-planes-python-armv7.tar.gz` from the
   [latest release](https://github.com/azilnik/kindle-planes/releases/latest), checks it,
   and unpacks it beside `/mnt/us/python`, tests it, then swaps it in and marks it `INSTALLED`.
   Skipped once a complete copy is there; a copy cut off halfway is never mistaken for one.
2. **Config.** Writes `/mnt/us/sky/config.json` if there is none, from `sky/config.json`
   or `sky/config-pw2.json`. Yours is never replaced; `--home` only sets `lat` and `lon` in it.
3. **Boot job.** Copies `sky.conf` to `/etc/upstart/`. It starts the display 45 seconds
   after the Kindle's UI on every boot. To keep the display off across reboots, create
   `/mnt/us/sky/DISABLED`.
4. **Code.** Runs `tools/deploy.sh`, which copies `sky/` and starts the loop.

Over an install from when this project was kindle-planes (`/mnt/us/planes`), it first stops
that one and moves its `config.json`, gift letter, orbits and power log to `/mnt/us/sky`,
then removes the old code and boot job.

Then set `heading` and `tz` in `config.json` ([configuration.md](configuration.md)). The
shipped `safe` fits the printed inserts; if yours differs, measure it with
[the test pattern](frame.md#measure-what-the-mat-hides).

### About the Python bundle

It's [python-build-standalone](https://github.com/astral-sh/python-build-standalone) 3.12
for `armv7-unknown-linux-gnueabihf`, with Pillow and requests installed. Pillow is the part
that can't come from PyPI: the Kindle's libc is glibc 2.20, so it's built in a Debian
jessie container, with zlib and FreeType only. To build it yourself, with Docker running:
`build/bundle.sh <URL of the Python tarball>`, then `BUNDLE=out/py/kindle-planes-python-armv7.tar.gz tools/install.sh`.

The user store is FAT, so there are no symlinks: call `/mnt/us/python/bin/python3.12` by
its full name (`run.sh` does). Pillow's `stroke_width` segfaults against the Kindle's
FreeType; draw any outline by offsetting text instead.

## Controls

| | |
|---|---|
| Stop and get the Kindle UI back | `ssh kindle sh /mnt/us/sky/run.sh stop`, or press power twice ([configuration.md](configuration.md#the-power-button)) |
| Restart the display | `ssh kindle sh /mnt/us/sky/run.sh restart` |
| First install | `tools/install.sh --home LAT,LON` |
| Deploy code | `tools/deploy.sh` (waits for a Wi-Fi window) |
| Keep it awake while iterating | `tools/deploy.sh --hold`, then `rm /mnt/us/sky/HOLD` |
| Screenshot | `tools/fbshot.sh out/kindle.png` |
| Test pattern | `tools/grid.sh`, then `tools/grid.sh done` |
| Logs | `/tmp/sky.log` on the device; battery in `/mnt/us/sky/power.log` |
| Another Kindle | Every tool takes `KINDLE=host`, e.g. `KINDLE=kindle2 tools/deploy.sh` |

## What's on the Kindle

| Where | What |
|---|---|
| `/mnt/us/sky/` | The code, fonts and star catalog, copied by `tools/deploy.sh` |
| `/mnt/us/sky/config.json` | Your settings. A deploy never overwrites it |
| `/mnt/us/sky/orbits.csv`, `balloon.json` | Satellite orbits, and the weather balloon's track so far |
| `/mnt/us/sky/gift.txt`, `gift.seen`, `gift.date` | A gift letter, if there is one ([sky.md](sky.md#give-it-as-a-gift)) |
| `/mnt/us/sky/power.log` | Battery readings, summarized by `tools/battery.py` |
| `/mnt/us/python/` | Python 3.12 with Pillow and requests |
| `/etc/upstart/sky.conf` | Starts the display on boot |
| `/tmp/sky.log` | Errors. Cleared on reboot |

The Kindle asks CelesTrak for satellite orbits, SondeHub for weather balloons near `lat`,
`lon`, and Open-Meteo for cloud cover on meteor shower nights. Nothing else leaves it. To
remove everything, delete the two folders and `/etc/upstart/sky.conf`.

## Paperwhite 2

A 2013 Paperwhite (serial starting B0D4 or 90D4) runs the same code. What's different:

1. **Jailbreak.** Its firmware stops at 5.12.2.2. [WinterBreak2](https://kindlemodding.org/jailbreaking/WinterBreak2/)
   works: copy its `winterbreak2` folder to the Kindle, open
   `https://penguins184.xyz/wb2` in the Experimental Browser, tap Jailbreak. A factory
   reset wipes that folder, so copy it again after one.
2. **SSH.** USBNetLite only ships builds for firmware 5.16.3 and newer. `build/dropbear.sh`
   builds a static dropbear that runs on older firmware. Put `dropbearmulti` and your
   public key (as `authorized_keys`) in `/mnt/us/kindle-ssh/`, and
   `build/install-ssh-dropbear.sh` in `documents/`, then open it from the library. It
   writes the IP to `kindle-ssh/ip.txt`. Keys live in `/etc/kindle-ssh`: dropbear refuses
   them under `/var/local`, which other users can write to.
3. **Python.** No prebuilt Python starts on its 3.0 kernel.
   `build/python-softfloat.sh` builds one from source (a couple of hours), then
   `FLOAT=soft build/bundle.sh unused` packs it with Pillow. Install with
   `BUNDLE=out/py-soft/kindle-planes-python-armv7-softfloat.tar.gz KINDLE=kindle2 tools/install.sh`.
4. **Config.** `tools/install.sh` writes `sky/config-pw2.json`, with a wider text panel
   and the `safe` measured in the 13×18 insert. Deep sleep works as on a PW4: about 10 mA
   on average between redraws.

A frame takes about a second to draw, against a third of a second on a PW4: most of it is
scaling the canvas down to the smaller panel.
