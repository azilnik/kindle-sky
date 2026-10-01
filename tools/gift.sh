#!/bin/sh
# Give the sky frame as a gift: a letter on the screen until the first press of the power
# button, then the sky. Deploys, leaves the message on the Kindle and switches it to sky.
#   tools/gift.sh message.txt
# The message is plain text, paragraphs split by blank lines: the first is the greeting,
# the last the sign-off. It's rendered here first, to out/gift.png, to look at.
# The letter comes back every year on the day it was first opened, and it's also left in
# the Kindle's library as a book, "A letter for Amy" for a letter that opens "Dear Amy,".
# Run it again to put a letter back (and to start the yearly date over).
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
# The greeting's last word, letters only: "Dear Amy," is Amy
NAME=$(sed -n '/[^[:space:]]/{s/[,.!:;[:space:]]*$//;s/^.*[[:space:]]//;p;q;}' "$MSG" | tr -cd '[:alnum:]-')
BOOK="/mnt/us/documents/A letter for $NAME.txt"
ssh "$KINDLE" 'cat > /mnt/us/planes/gift.txt && rm -f /mnt/us/planes/gift.seen /mnt/us/planes/gift.date' < "$MSG"
ssh "$KINDLE" "cat > '$BOOK' && rm -f /mnt/us/planes/HOLD" < "$MSG"
ssh "$KINDLE" 'sh /mnt/us/planes/run.sh frame sky >/dev/null'
echo "wrapped: the Kindle shows the letter until someone presses its power button"
echo "and keeps it in its library as \"A letter for $NAME\""
