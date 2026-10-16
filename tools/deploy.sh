#!/bin/sh
# Push sky/ to the Kindle and restart the loop. The Kindle is the `kindle` host in
# ~/.ssh/config (set KINDLE to use another name).
# In power-save mode Wi-Fi is only up for a few seconds every 5 minutes, so this waits
# for that window, drops HOLD to keep it awake, copies, then releases HOLD (unless --hold).
#   tools/deploy.sh [--hold]
set -e
cd "$(dirname "$0")/../sky"
KINDLE=${KINDLE:-kindle}
IP=$(ssh -G "$KINDLE" | awk '/^hostname /{print $2}')
case "$1" in
    ''|--hold) KEEP_HOLD=$1 ;;
    *) echo "usage: tools/deploy.sh [--hold]"; exit 1 ;;
esac
if ! ssh -o ConnectTimeout=3 "$KINDLE" true 2>/dev/null; then
    echo "waiting for the Kindle's next Wi-Fi window (or press its power button once)..."
    until nc -z -G 1 "$IP" 22 2>/dev/null && \
          ssh -o ConnectTimeout=3 "$KINDLE" 'mkdir -p /mnt/us/sky; touch /mnt/us/sky/HOLD; lipc-set-prop com.lab126.cmd wirelessEnable 1' 2>/dev/null; do
        sleep 0.5
    done
    sleep 4
fi
# config.json and the files written at runtime stay on the device
COPYFILE_DISABLE=1 tar cf - --exclude 'power.log*' --exclude ssh.log --exclude 'orbits.csv*' --exclude 'balloon.json*' \
    --exclude __pycache__ --exclude samples --exclude make.py --exclude 'config*.json' --exclude HOLD --exclude DISABLED \
    --exclude 'gift.*' . |
    ssh "$KINDLE" 'mkdir -p /mnt/us/sky && cd /mnt/us/sky && tar xf -'
if [ "$KEEP_HOLD" = "--hold" ]; then
    ssh "$KINDLE" 'touch /mnt/us/sky/HOLD'
else
    ssh "$KINDLE" 'rm -f /mnt/us/sky/HOLD'
fi
ssh "$KINDLE" 'sh /mnt/us/sky/run.sh restart'
echo "deployed$([ "$KEEP_HOLD" = "--hold" ] && echo ' (held awake: rm /mnt/us/sky/HOLD to resume power saving)')"
