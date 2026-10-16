#!/bin/sh
# Everything to run before a commit, with no Kindle and no network: lint, the screen loop
# on a fake clock, and every sample rendered as each Kindle sees it, on the oldest Python
# and Pillow the code supports. Look at out/sheet.png and out/sheet-pw2.png afterwards.
set -e
cd "$(dirname "$0")/.."
# The Mac's LibreSSL makes urllib3 warn on import; nothing here touches the network
export PYTHONWARNINGS=ignore
PY="uv run -q --python 3.9 --with pillow==9.0.1 --with requests python"
uvx ruff check sky tools insert
$PY tools/simulate.py
$PY sky/samples/sheet.py out/sheet.png
$PY sky/samples/sheet.py out/sheet-pw2.png --panel 758x1024 --config sky/config-pw2.json
$PY sky/sky.py --gift sky/samples/gift/letter.txt --rotate 0 --out out/gift.png >/dev/null
echo "all good: out/sheet.png, out/sheet-pw2.png, out/gift.png"
