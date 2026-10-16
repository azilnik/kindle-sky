#!/bin/sh
# Takes over the screen: stops the Kindle UI and runs sky.py, restarting it if it ever dies.
# `run.sh stop` (or a reboot with /mnt/us/sky/DISABLED present) hands the screen back.
# `run.sh restart` starts it over, as a deploy does.
DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE=/tmp/sky.pid
PY=/mnt/us/python/bin/python3.12
# Reader-side services nothing here uses; KOReader stops this same set on PW4 5.18.1
READER="stored webreader kfxreader kfxview todo tmd rcm archive scanner otav3 otaupd"

if [ "$1" = "restart" ]; then
    [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null
    rm -f "$PIDFILE"
    exec sh "$0"
fi

if [ "$1" = "stop" ]; then
    [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null
    rm -f "$PIDFILE"
    touch /tmp/sky.stopped
    lipc-set-prop com.lab126.powerd preventScreenSaver 0
    start lab126_gui
    # The library and its books need these back (the gift's letter is one of them)
    for svc in $READER; do
        start "$svc" >/dev/null 2>&1
    done
    exit 0
fi

[ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null && exit 0

lipc-set-prop com.lab126.powerd preventScreenSaver 1
lipc-set-prop com.lab126.cmd wirelessEnable 1
stop lab126_gui 2>/dev/null
for svc in $READER; do
    stop "$svc" >/dev/null 2>&1
done
sleep 3

cd "$DIR"
rm -f /tmp/sky.stopped
: >/tmp/sky.log
# Supervised: if the frame ever exits on an error nothing caught, start it again, waiting
# longer each time it fails quickly so a broken build doesn't spin. `run.sh stop`, or a kill
# of this loop's pid (deploy.sh, grid.sh), ends the loop and takes the frame with it
(
    trap '' HUP
    trap 'kill $child 2>/dev/null; exit 0' TERM INT
    delay=30
    while :; do
        began=$(date +%s)
        # Toronto unless config.json sets "tz"
        TZ="EST5EDT,M3.2.0,M11.1.0" SSL_CERT_FILE="$DIR/cacert.pem" REQUESTS_CA_BUNDLE="$DIR/cacert.pem" \
            "$PY" sky.py "$@" &
        child=$!
        wait $child
        code=$?
        [ -f /tmp/sky.stopped ] && exit 0
        [ $(( $(date +%s) - began )) -gt 600 ] && delay=30
        echo "$(date) sky.py exited ($code), restarting in $delay s"
        # Waited on, not run in the foreground, so a stop doesn't sit out the sleep
        sleep $delay &
        child=$!
        wait $child
        delay=$(( delay * 2 > 900 ? 900 : delay * 2 ))
    done
# Its own output to the log too: the shell reports a killed frame ("Terminated"), and
# written to the SSH session that started it, long closed, that report would kill the loop
) </dev/null >>/tmp/sky.log 2>&1 &
echo $! >"$PIDFILE"
