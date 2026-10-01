#!/bin/sh
# Give the sky frame as a gift: a letter on the screen until the first press of the power
# button, then the sky. Deploys, leaves the message on the Kindle and switches it to sky.
#   tools/gift.sh message.txt
# The message is plain text, paragraphs split by blank lines: the first is the greeting,
# the last the sign-off. It's rendered here first, to out/gift.png, to look at.
# Run it again to put a letter back; the opened one waits on the Kindle as gift.seen.
set -e
[ -f "$1" ] || { echo "usage: tools/gift.sh message.txt"; exit 1; }
KINDLE=${KINDLE:-kindle}
MSG="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
# Render it here first: a letter too long for one screen stops before anything is sent
cd "$(dirname "$0")/.."
uv run -q --python 3.9 --with pillow==9.0.1 --with requests python planes/sky.py --gift "$MSG" --rotate 0 \
    --out out/gift.png 2>/dev/null || { echo "too long for one screen: shorten it and try again"; exit 1; }
echo "preview: out/gift.png"
tools/deploy.sh --hold
ssh "$KINDLE" 'cat > /mnt/us/planes/gift.txt && rm -f /mnt/us/planes/gift.seen /mnt/us/planes/HOLD' < "$MSG"
ssh "$KINDLE" 'sh /mnt/us/planes/run.sh frame sky >/dev/null'
echo "wrapped: the Kindle shows the letter until someone presses its power button"
