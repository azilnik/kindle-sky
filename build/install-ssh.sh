#!/bin/sh
# Name: Install SSH (USBNetLite)
# Author: kindle-sky
# UseHooks

# Installs USBNetLite (dropbear) from /mnt/us/claude-bootstrap with key-only login
# over Wi-Fi and autostart. Idempotent. on_install fires when the library indexes
# this file, so it may complete with zero taps.

CB=/mnt/us/claude-bootstrap
LOG="$CB/log.txt"

cb_setup() {
    mkdir /tmp/claude-setup.lock 2>/dev/null || { echo "already running"; return 0; }
    echo "=== claude-setup $(date)"
    if [ ! -x /mnt/us/usbnetlite/bin/dropbearmulti ]; then
        rm -rf /tmp/unl && mkdir -p /tmp/unl && cd /tmp/unl && tar xf "$CB/unl.tar"
        mntroot rw
        (. ./install.sh)
        echo "install rc=$?"
        mntroot ro
        cd /
    fi
    mkdir -p /mnt/us/usbnetlite/etc/dropbear
    cp -f "$CB/authorized_keys" /mnt/us/usbnetlite/etc/dropbear/authorized_keys
    sed -i 's/^ALLOW_PASSWORD_LOGIN=.*/ALLOW_PASSWORD_LOGIN="false"/' /mnt/us/usbnetlite/etc/config
    touch /mnt/us/usbnetlite/auto
    pidof dropbearmulti >/dev/null 2>&1 || sh /mnt/us/usbnetlite/bin/usbnetwork
    lipc-set-prop com.lab126.powerd preventScreenSaver 1 2>/dev/null
    IP=$(ifconfig wlan0 2>/dev/null | sed -n 's/.*inet addr:\([0-9.]*\).*/\1/p')
    echo "$IP" > "$CB/ip.txt"
    echo "SSH: $(pidof dropbearmulti >/dev/null 2>&1 && echo up || echo DOWN)   IP: ${IP:-none}"
    echo "DONE - tell Claude"
    rmdir /tmp/claude-setup.lock
}

on_install() { (cb_setup >>"$LOG" 2>&1 &) ; }
on_run() { cb_setup 2>&1 | tee -a "$LOG"; }
on_remove() { :; }
