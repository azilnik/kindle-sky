#!/usr/bin/env python3
"""Summarize the Kindle's power.log: measured drain, days per charge, and where awake
time goes. Usage: battery.py power.log [since_epoch]   (scp kindle:/mnt/us/sky/power.log .)"""
import sys
import time

with open(sys.argv[1]) as f:
    rows = [line.split() for line in f if line.strip()]
since = int(sys.argv[2]) if len(sys.argv) > 2 else 0
rows = [r for r in rows if int(r[0]) >= since]


def kv(r):
    return dict(x.split("=", 1) for x in r[2:] if "=" in x)


first, last = kv(rows[0]), kv(rows[-1])
hours = (int(rows[-1][0]) - int(rows[0][0])) / 3600.0
# The PW4's BD71827 reports charge in uAh, a PW2's MAX77696 in mAh (about 1400 when full)
per_mah = 1000.0 if int(first["charge"]) > 100000 else 1.0
used = (int(first["charge"]) - int(last["charge"])) / per_mah
print("window %.2f h  %s -> %s   on AC: %s" % (
    hours, time.strftime("%m-%d %H:%M", time.localtime(int(rows[0][0]))),
    time.strftime("%m-%d %H:%M", time.localtime(int(rows[-1][0]))), sorted({kv(r).get("ac") for r in rows})))
if hours and used > 0:
    ma = used / hours
    print("used %.0f mAh  ->  %.1f mA average  ->  %.1f days per 1500 mAh charge" % (used, ma, 1500 / ma / 24))
fetch = [kv(r) for r in rows if r[1] == "fetch"]
draw = [kv(r) for r in rows if r[1] == "draw"]
if fetch:
    print("fetches %d (%d failed), %.1f s awake each, %.1f s joining Wi-Fi" % (
        len(fetch), sum(f["ok"] != "1" for f in fetch),
        sum(float(f["awake_s"]) for f in fetch) / len(fetch),
        sum(max(0.0, float(f["wifi_s"])) for f in fetch) / len(fetch)))
if draw:
    print("draws %d, %.0f ms each" % (len(draw), sum(int(d["ms"]) for d in draw) / len(draw)))
