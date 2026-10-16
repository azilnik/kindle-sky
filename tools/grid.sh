#!/bin/sh
# Put the test pattern on the Kindle to measure `safe`, then hand the screen back.
# Press the Kindle's power button once first: that opens a 10-minute Wi-Fi window.
#   grid.sh          show the grid
#   grid.sh check    show the `safe` box from the Kindle's config.json
#   grid.sh done     back to the sky
set -e
cd "$(dirname "$0")/.."
KINDLE=${KINDLE:-kindle}

if [ "$1" = "done" ]; then
    ssh "$KINDLE" 'rm -f /mnt/us/sky/HOLD /tmp/grid.png; sh /mnt/us/sky/run.sh'
    echo "the sky is back within a minute"
    exit 0
fi

CFG=$(ssh -o ConnectTimeout=6 "$KINDLE" 'cat /mnt/us/sky/config.json') || {
    echo "can't reach the Kindle: press its power button once and try again"; exit 1; }
ROTATE=$(echo "$CFG" | sed -n 's/.*"rotate": *\([0-9]*\).*/\1/p')
SAFE=$(echo "$CFG" | tr -d ' \n' | sed -n 's/.*"safe":\[\([0-9,]*\)\].*/\1/p')
PANEL=$(ssh "$KINDLE" 'sed -n "s/^[A-Z]:\([0-9]*x[0-9]*\).*/\1/p" /sys/class/graphics/fb0/modes | head -1')
mkdir -p out
if [ "$1" = "check" ]; then
    [ -n "$SAFE" ] || { echo "no \"safe\" in the Kindle's config.json"; exit 1; }
    set -- --safe "$SAFE"
else
    set --
fi
uv run -q --python 3.9 --with 'pillow==9.0.1' python tools/grid.py "${ROTATE:-270}" out/grid.png \
    ${PANEL:+--panel "$PANEL"} "$@" >/dev/null

# The loop would draw over the pattern within a minute, so stop it; HOLD is left for
# `grid.sh done` to clear. fbink -w: wait for the panel, as loop.py does.
ssh "$KINDLE" 'touch /mnt/us/sky/HOLD; kill $(cat /tmp/sky.pid) 2>/dev/null; rm -f /tmp/sky.pid; cat > /tmp/grid.png
    for f in /mnt/us/libkh/bin/fbink /var/local/kmc/bin/fbink /mnt/us/usbnet/bin/fbink; do
        [ -x "$f" ] && exec "$f" -q -w -f -g file=/tmp/grid.png
    done
    exec fbink -q -w -f -g file=/tmp/grid.png' < out/grid.png
echo "showing out/grid.png on the Kindle. Photograph it straight on, then: tools/grid.sh done"
