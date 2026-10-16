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

`planes.py` looks for `fbink` at `/mnt/us/libkh/bin`, `/var/local/kmc/bin` and
`/mnt/us/usbnet/bin`. It comes with the KindleModding tool packages and with KOReader.

## 4. Install

Press the power button once so the Kindle stays on Wi-Fi, then:

```bash
tools/install.sh
```

It's safe to run again, and it does four things:

1. **Python.** Downloads `kindle-planes-python-armv7.tar.gz` from the
   [latest release](https://github.com/azilnik/kindle-planes/releases/latest), checks it,
   and unpacks it beside `/mnt/us/python`, tests it, then swaps it in and marks it `INSTALLED`.
   Skipped once a complete copy is there; a copy cut off halfway is never mistaken for one.
2. **Config.** Writes `/mnt/us/planes/config.json` if there is none. Yours is never replaced.
3. **Boot job.** Copies `planes.conf` to `/etc/upstart/`. It starts the display 45 seconds
   after the Kindle's UI on every boot. To keep the display off across reboots, create
   `/mnt/us/planes/DISABLED`.
4. **Code.** Runs `tools/deploy.sh`, which copies `planes/` and starts the loop.

Then set `lat`, `lon`, `city`, `airports` and `tz` in `config.json`
([configuration.md](configuration.md)), and measure `safe` with
[the test pattern](frame.md#measure-what-the-mat-hides).

### About the Python bundle

It's [python-build-standalone](https://github.com/astral-sh/python-build-standalone) 3.12
for `armv7-unknown-linux-gnueabihf`, with Pillow and requests installed. Pillow is the part
that can't come from PyPI: the Kindle's libc is glibc 2.20, so it's built in a Debian
jessie container, with zlib and FreeType only. To build it yourself, with Docker running:
`build/bundle.sh <URL of the Python tarball>`, then `BUNDLE=out/py/kindle-planes-python-armv7.tar.gz tools/install.sh`.

The user store is FAT, so there are no symlinks: call `/mnt/us/python/bin/python3.12` by
its full name (`run.sh` does). Pillow's `stroke_width` segfaults against the Kindle's
FreeType; the code draws halos by offsetting text instead.

## Controls

| | |
|---|---|
| Stop and get the Kindle UI back | `ssh kindle sh /mnt/us/planes/run.sh stop`, or press power twice (see README) |
| Switch style | `ssh kindle sh /mnt/us/planes/run.sh style detailed` |
| Switch frame | `ssh kindle sh /mnt/us/planes/run.sh frame sky` (or `planes`), or `tools/deploy.sh --frame sky` |
| First install | `tools/install.sh` |
| Deploy code | `tools/deploy.sh` (waits for a Wi-Fi window) |
| Keep it awake while iterating | `tools/deploy.sh --hold`, then `rm /mnt/us/planes/HOLD` |
| Screenshot | `tools/fbshot.sh out/kindle.png` |
| Test pattern | `tools/grid.sh`, then `tools/grid.sh done` |
| Logs | `/tmp/planes.log` on the device; battery in `/mnt/us/planes/power.log` |
| Another Kindle | Every tool takes `KINDLE=host`, e.g. `KINDLE=kindle2 tools/deploy.sh` |

## What's on the Kindle

| Where | What |
|---|---|
| `/mnt/us/planes/` | The code, fonts and shoreline, copied by `tools/deploy.sh` |
| `/mnt/us/planes/config.json` | Your settings. A deploy never overwrites it |
| `/mnt/us/planes/cache.json` | Routes and aircraft types already looked up |
| `/mnt/us/planes/tracks.json`, `traffic.json` | Today's positions for the night view, and counts for the traffic chart |
| `/mnt/us/planes/orbits.csv`, `balloon.json` | The sky frame's satellite orbits, and the weather balloon's track so far |
| `/mnt/us/planes/power.log` | Battery readings, summarized by `tools/battery.py` |
| `/mnt/us/python/` | Python 3.12 with Pillow and requests |
| `/etc/upstart/planes.conf` | Starts the display on boot |
| `/tmp/planes.log` | Errors. Cleared on reboot |

The Kindle sends nothing anywhere except requests for plane positions near `lat`, `lon`,
and for the routes of the planes it shows. The sky frame also asks CelesTrak for orbits
and SondeHub for weather balloons near `lat`, `lon`. To remove everything, delete the two folders and
`planes.conf`.

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
4. **Config.** Add `"panel_w": 560`, and measure `safe` with the test pattern
   (`KINDLE=kindle2 tools/grid.sh`) once it's in its frame. Deep sleep works as on a PW4:
   about 10 mA on average between frames.

A frame takes about a second to draw, against a third of a second on a PW4: most of it is
scaling the canvas down to the smaller panel.
