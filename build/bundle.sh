#!/bin/sh
# Builds the release bundle: Python 3.12 for the Kindle with Pillow and requests already
# installed, as one tarball that unpacks to /mnt/us/python. Needs Docker.
# Usage: build/bundle.sh PYTHON_TARBALL_URL
#   the cpython-3.12.*-armv7-unknown-linux-gnueabihf-install_only.tar.gz from
#   https://github.com/astral-sh/python-build-standalone/releases
# FLOAT=soft builds for firmware below 5.16.3 (PW2 and friends), which only has the
# soft-float loader: pass the ...-armv7-unknown-linux-gnueabi-install_only.tar.gz instead.
set -e
URL=${1:?usage: bundle.sh PYTHON_TARBALL_URL}
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ "${FLOAT:-hard}" = soft ]; then
    WORK="$HERE/../out/py-soft" OUT=kindle-sky-python-armv7-softfloat.tar.gz
    PLATFORM=linux/arm/v5 CHECK_IMAGE=arm32v5/debian:bookworm-slim
else
    WORK="$HERE/../out/py" OUT=kindle-sky-python-armv7.tar.gz
    PLATFORM=linux/arm/v7 CHECK_IMAGE=arm32v7/debian:bookworm-slim
fi
mkdir -p "$WORK"
cd "$WORK"
[ -f py312.tgz ] || curl -fL -o py312.tgz "$URL"

# Docker keeps one platform per tag, so fetch the right jessie before using it
docker pull -q --platform $PLATFORM debian/eol:jessie >/dev/null
docker run --rm --platform $PLATFORM -v "$WORK":/work -v "$HERE/pillow-armhf.sh":/build.sh:ro \
    debian/eol:jessie sh -c '
set -e
sh /build.sh
PY=/opt/python/bin/python3.12
$PY -m pip -q install --no-index --find-links /work/wheels pillow requests
$PY -c "import PIL._imaging, requests; print(\"Pillow\", PIL.__version__, \"requests\", requests.__version__)"
cd /opt/python
# Nothing the display uses, and most of the size
rm -rf lib/python3.12/test lib/python3.12/idlelib lib/python3.12/tkinter lib/python3.12/turtledemo \
    lib/python3.12/ensurepip lib/tcl* lib/tk* lib/itcl* lib/thread* share
find . -name __pycache__ -type d -prune -exec rm -rf {} +
# Aliases and build-time files, hard links to files kept anyway: packed as copies they
# doubled the bundle. run.sh calls python3.12 by its full name
rm -rf bin/python bin/python3 bin/python3-config bin/python3.12-config bin/2to3* bin/idle3* \
    bin/pydoc3* lib/libpython3.12.so lib/pkgconfig
# Static libpython and build Makefiles, for compiling against this Python: half the
# soft-float bundle. sysconfig reads _sysconfigdata, not these
rm -rf lib/python3.12/config-3.12-*
$PY -m pip list --format=freeze > /opt/python/BUNDLE.txt
# The Kindle user store is FAT and holds neither symlinks nor hard links: -h and
# --hard-dereference pack real files for both
cd /opt && tar -chzf /work/'"$OUT"' --hard-dereference python
'
# The container's kernel is new, so it can't catch a binary that needs a kernel helper the
# PW2's 3.0 kernel lacks (see python-softfloat.sh). Look for it instead
if [ "${FLOAT:-hard}" = soft ] && tar xzOf "$WORK/$OUT" | grep -qa __kernel_cmpxchg64; then
    echo "$OUT needs __kernel_cmpxchg64, which a PW2's kernel doesn't have"; exit 1
fi
if tar tvzf "$WORK/$OUT" | grep -q "^[hl]"; then
    echo "$OUT has links, which the Kindle's FAT store can't hold"; exit 1
fi

# Pillow 11 needs FreeType 2.6 or newer when it loads. The Kindle has that and jessie does
# not, so text can only be checked somewhere newer: unpack the bundle there and draw a frame
docker run --rm --platform $PLATFORM -v "$WORK":/work:ro -v "$HERE/../sky":/sky:ro \
    $CHECK_IMAGE sh -c '
set -e
apt-get update -qq && apt-get install -y -qq libfreetype6 >/dev/null
mkdir /mnt/us && tar xzf /work/'"$OUT"' -C /mnt/us
cp -r /sky /tmp/sky && cd /tmp/sky
/mnt/us/python/bin/python3.12 sky.py --sample samples/night.json --rotate 270 --out /tmp/frame.png
/mnt/us/python/bin/python3.12 -c "
from PIL import Image, features
im = Image.open(\"/tmp/frame.png\")
assert im.size == (1072, 1448), im.size
dark = sum(im.convert(\"L\").histogram()[:64])
assert dark > 20000, dark
print(\"frame ok\", im.size, \"dark px\", dark, \"freetype\", features.version(\"freetype2\"))"
'
shasum -a 256 "$OUT" | tee "$OUT.sha256"
ls -lh "$OUT"
