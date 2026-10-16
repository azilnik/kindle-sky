#!/bin/sh
# Name: Install SSH (dropbear)
# Author: kindle-sky
# UseHooks

# A scriptlet for Kindles on firmware below 5.16.3, where USBNetLite doesn't run. Installs
# the static dropbear from build/dropbear.sh, found in /mnt/us/kindle-ssh with your public
# key as authorized_keys. Key-only root login over Wi-Fi, started at every boot, and the
# Kindle's IP in /mnt/us/kindle-ssh/ip.txt. Safe to run again.

SRC=/mnt/us/kindle-ssh
DST=/var/local/ssh
# dropbear rejects keys in any folder that others can write to, or under one. /var/local
# belongs to the framework user and is group-writable, so the keys go on the root
# filesystem, where every folder is root's alone
KEYS=/etc/kindle-ssh
LOG=$SRC/log.txt

setup() {
    mkdir /tmp/kindle-ssh.lock 2>/dev/null || { echo "already running"; return 0; }
    echo "=== $(date)"
    mkdir -p $DST && chmod 700 $DST
    cp -f $SRC/dropbearmulti $DST/dropbearmulti && chmod 755 $DST/dropbearmulti
    [ -f $DST/host_ed25519 ] || $DST/dropbearmulti dropbearkey -t ed25519 -f $DST/host_ed25519 >/dev/null
    cat >$DST/start.sh <<EOF
#!/bin/sh
pidof dropbearmulti >/dev/null 2>&1 && exit 0
# The Kindle's firewall drops inbound TCP
iptables -C INPUT -p tcp --dport 22 -j ACCEPT 2>/dev/null || iptables -I INPUT -p tcp --dport 22 -j ACCEPT
# -s: no password logins
exec $DST/dropbearmulti dropbear -r $DST/host_ed25519 -D $KEYS -s -p 22 -P /tmp/dropbear.pid
EOF
    chmod 755 $DST/start.sh

    mntroot rw
    mkdir -p $KEYS && chmod 700 $KEYS
    cp -f $SRC/authorized_keys $KEYS/authorized_keys && chmod 600 $KEYS/authorized_keys
    cat >/etc/upstart/kindle-ssh.conf <<EOF
# SSH (dropbear) on every boot. Skip it by creating $SRC/DISABLED.
description "dropbear ssh"
start on started lab126_gui
task
script
    [ -f $SRC/DISABLED ] && exit 0
    sh $DST/start.sh
end script
EOF
    mntroot ro

    # Restart, so a second run picks up a new key or binary
    killall dropbearmulti 2>/dev/null
    sleep 1
    sh $DST/start.sh
    lipc-set-prop com.lab126.powerd preventScreenSaver 1 2>/dev/null
    sleep 1
    IP=$(ifconfig wlan0 2>/dev/null | sed -n 's/.*inet addr:\([0-9.]*\).*/\1/p')
    echo "$IP" > $SRC/ip.txt
    echo "SSH: $(pidof dropbearmulti >/dev/null 2>&1 && echo up || echo DOWN)   IP: ${IP:-none}"
    rmdir /tmp/kindle-ssh.lock
}

on_install() { (setup >>"$LOG" 2>&1 &) ; }
on_run() { setup 2>&1 | tee -a "$LOG"; }
on_remove() { :; }
