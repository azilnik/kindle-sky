"""Kindle power controls: Wi-Fi duty cycling, CPU governor, sleeping between ticks,
and a battery log to measure what each change is worth. Every call is a no-op off
the Kindle so the renderer still runs on a laptop.

Nothing here is on by default. config.json "power" turns pieces on once each one has
been verified on the device:
    {"wifi_toggle": true, "governor": "powersave", "suspend": false}
"""

import errno
import glob
import os
import select
import socket
import struct
import subprocess
import time

KINDLE = os.path.exists("/usr/bin/lipc-set-prop")


def _find(pattern, fallback):
    found = sorted(glob.glob(pattern))
    return found[0] if found else fallback


def _snvs_rtc():
    # The SoC's SNVS RTC is the one that wakes a PW4 from suspend-to-RAM; its PMIC's RTC does
    # not. Confirmed by travismorton1995/kindle-dash and katadelos/ktrmnl. It's rtc1 on a PW4
    # and rtc2 on a PW2, so find it by name.
    for rtc in sorted(glob.glob("/sys/class/rtc/rtc*")):
        try:
            with open(rtc + "/name") as f:
                if "snvs" in f.read():
                    return rtc + "/wakealarm"
        except OSError:
            pass
    return "/sys/class/rtc/rtc1/wakealarm"


WAKEALARM = _snvs_rtc()
# While this file exists the loop never suspends and keeps Wi-Fi up, so SSH stays reachable.
HOLD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "HOLD")
# PW4: a ROHM BD71827 power chip. PW2: a Maxim MAX77696. Same files, different names
BAT = _find("/sys/class/power_supply/*_bat", _find("/sys/class/power_supply/*-battery", ""))
AC_ONLINE = _find("/sys/class/power_supply/*_ac", _find("/sys/class/power_supply/*-charger", "")) + "/online"
# The MAX77696's charger "online" can stick at 1 after the power goes away: a PW2 sat
# "charging" on battery for hours, light on and never suspending. Its USB controller's
# VBUS reading is the truth. A PW4 has no such file and trusts "online"
VBUS = _find("/sys/class/power_supply/*-uic/device/vbvolt", "")
BACKLIGHT = _find("/sys/class/backlight/*", "/sys/class/backlight/bl") + "/brightness"
# build/install-ssh-dropbear.sh's starter; it exits at once if dropbear is already up
SSH_START = "/var/local/ssh/start.sh"
SSH_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ssh.log")
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "power.log")
LOG_MAX = 256 * 1024
# Both report KEY_POWER on a PW4 (SoC SNVS and the BD71827 PMIC); watch both. On a PW2
# event0 is the power key and event1 the touchscreen, which never sends KEY_POWER
POWER_KEYS = ("/dev/input/event0", "/dev/input/event1")
KEY_POWER = 116


def _lipc_set(service, prop, value):
    subprocess.call(["lipc-set-prop", service, prop, str(value)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _lipc_get(service, prop):
    try:
        return subprocess.check_output(["lipc-get-prop", service, prop],
                                       stderr=subprocess.DEVNULL).decode().strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def set_governor(name):
    if not KINDLE or not name:
        return
    try:
        with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor", "w") as f:
            f.write(name)
    except OSError:
        pass


def wifi_up(timeout=40, reset=False):
    """Turn Wi-Fi on and wait until wifid reports a connection. Returns seconds taken,
    or None on timeout. reset=True power-cycles the radio and connection manager first,
    which is what unsticks wifid after it gives up on a network. A no-op (0) off the Kindle."""
    if not KINDLE:
        return 0.0
    start = time.time()
    if reset:
        _lipc_set("com.lab126.wifid", "enable", 0)
        _lipc_set("com.lab126.cmd", "wirelessEnable", 0)
        time.sleep(2)
    if _lipc_get("com.lab126.wifid", "cmState") != "CONNECTED":
        # Both switches: wirelessEnable is the radio, wifid enable the connection manager
        _lipc_set("com.lab126.cmd", "wirelessEnable", 1)
        _lipc_set("com.lab126.wifid", "enable", 1)
    while time.time() - start < timeout:
        if _lipc_get("com.lab126.wifid", "cmState") == "CONNECTED":
            return time.time() - start
        time.sleep(0.5)
    return None


_frontlight = None


def set_frontlight(level):
    """0-24 on powerd's scale. Only calls out when the level changes."""
    global _frontlight
    lit = _read(BACKLIGHT) not in ("", "0")
    # Re-apply if the hardware disagrees (suspend can switch the LEDs off behind powerd)
    if KINDLE and (level != _frontlight or bool(level) != lit):
        _lipc_set("com.lab126.powerd", "flIntensity", int(level))
        _frontlight = level


def on_ac():
    return KINDLE and _read(AC_ONLINE) == "1" and (not VBUS or _read(VBUS) == "1")


def restart_wifid():
    """Heavier than a radio cycle: restart the connection manager itself."""
    if KINDLE:
        subprocess.call(["restart", "wifid"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def start_ssh():
    """Start SSH unless something already answers on port 22. The boot job can race the
    Kindle UI it stops and leave it down, so the loop checks at launch, every fetch and on a
    button press. start.sh's own check (any dropbearmulti process) passes for a stuck one,
    hence the kill. A no-op where SSH is USBNetLite (a PW4): no start.sh of its own here."""
    if not KINDLE or not os.path.exists(SSH_START) or _listening(22):
        return
    subprocess.call(["killall", "dropbearmulti"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # To a file, not a pipe: dropbear forks into the background holding whatever it was given
    with open(SSH_LOG, "w") as out:
        rc = subprocess.call(["sh", "-x", SSH_START], stdout=out, stderr=out)
    time.sleep(1)
    log("ssh_start", rc=rc, up=int(_listening(22)))


def _listening(port):
    s = socket.socket()
    s.settimeout(1)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def reboot():
    """Last resort for an unattended display. The upstart job restarts the loop on boot."""
    if KINDLE:
        log("reboot")
        os.sync()
        subprocess.call(["reboot"])


def wifi_down():
    """Radio off, then wait for wifid to finish tearing down so the driver isn't
    suspended mid-disconnect."""
    if KINDLE and not held():
        _lipc_set("com.lab126.cmd", "wirelessEnable", 0)
        start = time.time()
        while time.time() - start < 5 and _lipc_get("com.lab126.wifid", "cmState") == "CONNECTED":
            time.sleep(0.25)
        time.sleep(0.5)


def held():
    return os.path.exists(HOLD)


def battery():
    """(percent, µAh left, µA average draw; negative = discharging, AC online)."""
    if not KINDLE:
        return None
    return (_read(BAT + "/capacity"), _read(BAT + "/charge_now"),
            _read(BAT + "/current_avg"), "1" if on_ac() else "0")


def log(event, **fields):
    """One line per event: epoch, event, battery snapshot, extra fields. Rotates at LOG_MAX."""
    if not KINDLE:
        return
    bat = battery() or ("", "", "", "")
    line = "%d %s cap=%s charge=%s avg=%s ac=%s %s\n" % (
        time.time(), event, bat[0], bat[1], bat[2], bat[3],
        " ".join("%s=%s" % kv for kv in sorted(fields.items())))
    # OSError: the log is diagnostics, and the user store can vanish under it (Drive Mode).
    # Two tries: on a fresh install there is no log to measure yet, and it must still start
    try:
        if os.path.getsize(LOG) > LOG_MAX:
            os.replace(LOG, LOG + ".1")
    except OSError:
        pass
    try:
        with open(LOG, "a") as f:
            f.write(line)
    except OSError:
        pass


def sleep_until(when, suspend=False):
    """Idle until `when` (epoch). With suspend on, the Kindle deep-sleeps and the RTC
    alarm wakes it. Returns "rtc", "button" (woke early: someone pressed power), "idle", or
    "refused" when the kernel wouldn't suspend and it waited awake instead."""
    while True:
        left = when - time.time()
        if left <= 0:
            return "idle"
        if not (suspend and KINDLE and left > 8 and not held()):
            return _wait_awake(when)
        went = time.time()
        woke = _suspend(when)
        if woke != "early":
            return woke
        # Woken by something else, so sleep again for what's left. A solar panel in weak
        # light hovers at the charger's threshold and sets off its interrupt over a hundred
        # times a second (PW2, 2026-10-09): when it wakes at once, wait awake instead
        if time.time() - went < 2:
            return _wait_awake(when)


def _open_keys():
    fds = []
    for path in POWER_KEYS if KINDLE else ():
        try:
            fds.append(os.open(path, os.O_RDONLY | os.O_NONBLOCK))
        except OSError:
            pass
    return fds


def _pressed(fd):
    try:
        data = os.read(fd, 16 * 64)
    except OSError:
        return False
    # struct input_event on armhf: timeval (2 x int32), type, code (u16), value (s32)
    for i in range(0, len(data) - 15, 16):
        etype, code, value = struct.unpack_from("HHi", data, i + 8)
        if etype == 1 and code == KEY_POWER and value == 1:
            return True
    return False


def _wait_awake(when):
    """Sleep awake until `when`, returning "button" early if power is pressed."""
    fds = _open_keys()
    try:
        while True:
            left = when - time.time()
            if left <= 0:
                return "idle"
            if not fds:
                time.sleep(left)
                return "idle"
            for fd in select.select(fds, [], [], left)[0]:
                if _pressed(fd):
                    return "button"
    finally:
        for fd in fds:
            os.close(fd)


def _suspend(when):
    seconds = int(when - time.time() + 0.999)
    try:
        # The kernel refuses to overwrite a pending alarm, so clear it first
        with open(WAKEALARM, "w") as f:
            f.write("0")
        with open(WAKEALARM, "w") as f:
            f.write("+%d" % seconds)
        with open(WAKEALARM) as f:
            armed = f.read().strip()
        err = "" if armed else "unarmed"
    except OSError as e:
        armed, err = "", errno.errorcode.get(e.errno, e.errno)
    if not armed:
        # Never suspend without a wake-up armed: that sleeps until someone presses power
        log("suspend_refused", step="alarm", err=err)
        return _refused(when)
    os.sync()
    # Open across the suspend, so the press that wakes it is waiting to be read
    fds = _open_keys()
    try:
        with open("/sys/power/state", "w") as f:
            f.write("mem")  # blocks until resume
    except OSError as e:
        # A PW2 once stopped suspending after a wifid restart and sat awake at ~25 mA until
        # the battery died, without a word in the log. Say why; the loop reboots if it lasts
        log("suspend_refused", step="mem", err=errno.errorcode.get(e.errno, e.errno))
        return _refused(when)
    finally:
        pressed = any([_pressed(fd) for fd in fds])
        for fd in fds:
            os.close(fd)
    if pressed:
        return "button"
    if time.time() >= when - 5:
        # The alarm has one-second resolution and tends to fire just early; wait out the
        # remainder here so the loop doesn't draw the same minute twice
        time.sleep(max(0, when - time.time()))
        return "rtc"
    # Early with no press read. On a charger that's its interrupt; on battery, nothing else
    # wakes it, so count it as the power button in case the press was missed
    return "early" if on_ac() else "button"


def _refused(when):
    # Awake, but still listening for the power button
    return "button" if _wait_awake(when) == "button" else "refused"
