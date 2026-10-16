# build

Scripts from setting up the Kindles, kept for the next one. Steps in
[docs/device-setup.md](../docs/device-setup.md).

- `install-ssh.sh`: a KUAL scriptlet. Installs USBNetLite (dropbear) from
  `/mnt/us/claude-bootstrap/` with key-only root login over Wi-Fi, started at boot.
- `pillow-armhf.sh`: builds Pillow 11.3 and downloads `requests` wheels for the Kindle's
  Python 3.12, inside a Debian jessie armv7 container so the result links against a glibc
  older than the Kindle's.
- `bundle.sh`: runs `pillow-armhf.sh`, installs the result into that Python, and packs it
  as `kindle-sky-python-armv7.tar.gz` with symlinks replaced by files, since the
  Kindle's FAT store can't hold them. This is the file attached to each release.
- `dropbear.sh`, `install-ssh-dropbear.sh`: SSH for firmware below 5.16.3 (a Paperwhite 2),
  where USBNetLite doesn't run. A static soft-float dropbear built from its author's
  source, and the scriptlet that installs it.
- `python-softfloat.sh`: Python 3.12 for the same Kindles, from source. Their 3.0 kernel
  lacks the helper every prebuilt soft-float Python needs for 64-bit atomics. Then
  `FLOAT=soft bundle.sh` packs it as `kindle-sky-python-armv7-softfloat.tar.gz`.
