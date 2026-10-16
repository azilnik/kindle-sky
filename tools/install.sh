#!/bin/sh
# Install the sky frame on a jailbroken Kindle that answers to `ssh kindle`
# (docs/device-setup.md). Works out which Kindle it is, puts Python on it, copies the code,
# writes a config.json if there is none, installs the boot job and starts the display.
# Safe to run again; over an old kindle-planes install, it moves that one's settings over.
#   tools/install.sh [--home LAT,LON] [--hold]
#     --home   where the sky is seen from, for a new config.json (default: Toronto)
#     --hold   keep the Kindle awake on Wi-Fi afterwards, as tools/deploy.sh --hold does
#   KINDLE=kindle2 tools/install.sh     another Kindle, by its ~/.ssh/config name
#   BUNDLE=path/to/bundle.tar.gz         a local Python bundle (build/bundle.sh)
# Press the Kindle's power button once first so it stays on Wi-Fi.
set -e
cd "$(dirname "$0")/.."
KINDLE=${KINDLE:-kindle}
RELEASE=${RELEASE:-https://github.com/azilnik/kindle-planes/releases/latest/download}
HOME_AT= HOLD=
while [ $# -gt 0 ]; do
    case "$1" in
        --home) HOME_AT=$2; shift ;;
        --hold) HOLD=--hold ;;
        *) echo "usage: tools/install.sh [--home LAT,LON] [--hold]"; exit 1 ;;
    esac
    shift
done
if [ -n "$HOME_AT" ]; then
    LAT=${HOME_AT%%,*} LON=${HOME_AT#*,}
    echo "$LAT $LON" | grep -Eq '^-?[0-9]+(\.[0-9]+)? -?[0-9]+(\.[0-9]+)?$' || {
        echo "--home takes LAT,LON in degrees, like 43.65,-79.38"; exit 1; }
fi

ssh -o ConnectTimeout=6 "$KINDLE" true || {
    echo "can't reach the Kindle: press its power button once and try again"; exit 1; }

ssh "$KINDLE" 'for f in /mnt/us/libkh/bin/fbink /var/local/kmc/bin/fbink /mnt/us/usbnet/bin/fbink; do
    [ -x "$f" ] && exit 0; done; command -v fbink >/dev/null' || {
    echo "no fbink on the Kindle: see docs/device-setup.md, FBInk"; exit 1; }

# Firmware 5.16.3 and newer is hard-float; older firmware (a PW2 tops out at 5.12) has only
# the soft-float loader and needs the other bundle
if ssh "$KINDLE" '[ -e /lib/ld-linux-armhf.so.3 ]'; then
    NAME=kindle-planes-python-armv7.tar.gz
else
    NAME=kindle-planes-python-armv7-softfloat.tar.gz
fi
# A PW2's 758x1024 panel starts from its own config: a wider text panel, and the safe area
# measured in the 13x18 insert
case $(ssh "$KINDLE" 'cat /sys/class/graphics/fb0/modes') in
    *758x1024*) MODEL="Paperwhite 2" CONFIG=sky/config-pw2.json ;;
    *) MODEL="Paperwhite 4" CONFIG=sky/config.json ;;
esac
echo "kindle: $MODEL"

# INSTALLED is written only after a complete, tested copy: an install cut off halfway can
# still import PIL and requests, so a working import proves nothing
if ssh "$KINDLE" "[ -f /mnt/us/python/INSTALLED ]" 2>/dev/null; then
    echo "python: already there"
else
    if [ -z "$BUNDLE" ]; then
        mkdir -p out
        BUNDLE=out/$NAME
        echo "python: downloading"
        curl -fL --progress-bar -o "$BUNDLE" "$RELEASE/$NAME" || {
            echo "can't download $NAME from $RELEASE: is there a published release?"; exit 1; }
        curl -fsSL -o "$BUNDLE.sha256" "$RELEASE/$NAME.sha256"
        (cd out && shasum -a 256 -c "$NAME.sha256" >/dev/null) || {
            echo "the download doesn't match its checksum"; exit 1; }
    fi
    echo "python: copying to the Kindle, a few minutes"
    # Beside the old one, then swapped in once it works, so a cut-off copy never replaces
    # a good Python and is never mistaken for one
    ssh "$KINDLE" 'rm -rf /mnt/us/python.new && mkdir /mnt/us/python.new && cd /mnt/us/python.new && tar xzf -' < "$BUNDLE"
    ssh "$KINDLE" '/mnt/us/python.new/python/bin/python3.12 -c "import json, ssl, zlib, requests, PIL.Image, PIL.ImageFont" &&
        rm -rf /mnt/us/python && mv /mnt/us/python.new/python /mnt/us/python && rmdir /mnt/us/python.new &&
        touch /mnt/us/python/INSTALLED' || { echo "python: the copy on the Kindle doesn't work, not installed"; exit 1; }
fi

# This project was kindle-planes, in /mnt/us/planes with a boot job of that name. Stop it
# and bring its settings, its gift letter and its logs over; the planes code goes
ssh "$KINDLE" 'set -e
    [ -d /mnt/us/planes ] || exit 0
    touch /tmp/planes.stopped
    [ -f /tmp/planes.pid ] && kill $(cat /tmp/planes.pid) 2>/dev/null || true
    mkdir -p /mnt/us/sky
    for f in config.json gift.txt gift.seen gift.date orbits.csv balloon.json power.log; do
        [ -f /mnt/us/planes/$f ] && [ ! -f /mnt/us/sky/$f ] && mv /mnt/us/planes/$f /mnt/us/sky/$f
    done
    mntroot rw >/dev/null 2>&1; rm -f /etc/upstart/planes.conf; mntroot ro >/dev/null 2>&1
    rm -rf /mnt/us/planes
    echo "moved: the old kindle-planes install, settings kept"'

# deploy.sh never touches config.json, so a first install has to write one
ssh "$KINDLE" 'mkdir -p /mnt/us/sky'
if ssh "$KINDLE" '[ -f /mnt/us/sky/config.json ]'; then
    echo "config: keeping the Kindle's own"
else
    ssh "$KINDLE" 'cat > /mnt/us/sky/config.json' < "$CONFIG"
    echo "config: written from $CONFIG"
fi
if [ -n "$HOME_AT" ]; then
    ssh "$KINDLE" "sed -i -e 's/\"lat\": *[-0-9.]*/\"lat\": $LAT/' -e 's/\"lon\": *[-0-9.]*/\"lon\": $LON/' /mnt/us/sky/config.json"
    echo "home: $LAT, $LON"
elif ssh "$KINDLE" 'grep -q "\"lat\": *43.6535" /mnt/us/sky/config.json'; then
    echo "home: Toronto City Hall, the default. Set yours with --home LAT,LON"
fi

# The boot job lives on the root filesystem, which is read-only until asked
ssh "$KINDLE" 'mntroot rw >/dev/null 2>&1; cat > /etc/upstart/sky.conf; rc=$?; mntroot ro >/dev/null 2>&1; exit $rc' \
    < sky/sky.conf
echo "boot job: installed"

tools/deploy.sh $HOLD
echo "The sky within a minute. Settings: /mnt/us/sky/config.json, see docs/configuration.md"
