# Power

Measured on a Paperwhite 4 on battery, unless the row says otherwise. `tools/battery.py
power.log` prints these numbers from the device's log.

| Setup | Draw | Per charge |
|---|---|---|
| In the frame (27 h measured, 2026-10-01 to 02): 5 mA by day, 3.5 mA at night | 4.7 mA | ~13 days |
| Paperwhite 2 in the frame, deep sleep between redraws (2026-09-30) | ~10 mA | ~5.5 days of its ~1400 mAh |

A Paperwhite 2 spends about a second awake per redraw, against a third of a second on a
Paperwhite 4: most of it is scaling the canvas down to its smaller panel (`turn()`).

The project started as a planes frame that fetched flight positions every 5 to 10 minutes.
Its measurements are how the loop got this frugal:

| Setup | Draw | Per charge |
|---|---|---|
| Kindle UI stopped, Wi-Fi always on, redraw every 20 s | ~84 mA | ~18 h |
| Suspend between redraws, Wi-Fi only for fetches | 20.5 mA | ~3 days |
| Plus waiting for the e-ink refresh and Wi-Fi teardown before suspend | 13.5 mA | ~5 days |
| Planes, in the frame, day-to-day (Wi-Fi about 190 times a day) | ~11 mA | ~5.5 days |

The sky needs a fraction of that: it computes most of what it shows, so Wi-Fi goes on about
65 times a day, around the two daily weather balloon launches and every few hours otherwise.

## What the loop does

- Redraws every 10 minutes as the sky turns, and every minute while something crosses it.
- Fetches only when something is due: orbits once a day, balloons around launches and every
  few hours, cloud cover on meteor shower nights. Wi-Fi is on only for the fetch.
- Suspends to RAM between, woken by the SoC's SNVS RTC (`rtc1` on a PW4, `rtc2` on a PW2;
  the power chip's own RTC doesn't wake them).
- Night: no fetching, a redraw every half hour.
- Near-empty battery: parks on a last drawing with "Battery low", since e-ink keeps the last
  image after power is gone. Comes back at 10% or on a charger.
- On a charger: Wi-Fi stays up, no suspend, the front light on, and the screen changes only
  when what it says does.

## What each fix was worth

A redraw went from ~1.5 s to ~0.35 s of awake time: cache rasterized text and icons, write
PGM instead of PNG (7 ms instead of 500), transpose instead of rotate.

Suspending while the screen was still refreshing hung the kernel about every 7th sleep and
the watchdog rebooted the Kindle every ~12 minutes. `fbink -w` (wait for the panel) and
waiting for `wifid` to drop before suspending fixed it.

`wifid` can lose the network overnight and never retry. Failures escalate: radio cycle every
3rd failure, restart `wifid` after about an hour, reboot after about three. A kernel that
refuses to suspend for 20 minutes straight also gets a reboot, and SSH is restarted
whenever its port stops answering.

Fetches used to fail when `wifid` reported connected before the link carried traffic. The
fetch now retries twice within the same wake instead of paying for another Wi-Fi join.

A Paperwhite 2's charger chip can keep saying it's plugged in after the cable is gone, which
kept the light on and the Kindle awake until the battery died. The loop trusts the USB
controller's voltage reading instead. A solar panel in weak light hovers at the charger's
threshold and wakes the Kindle many times a second; a wake that comes straight back sleeps
awake instead.
