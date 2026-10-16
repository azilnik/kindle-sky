#!/usr/bin/env python3
"""Fetch the sky frame's icon fonts and cut them down to the glyphs it uses.
Run on the Mac:  uv run --with fonttools python tools/icon_fonts.py
Writes planes/fonts/{phosphor-fill,tabler-filled,weather-icons}.ttf, their licenses,
and planes/fonts/icons.json (icon name -> [font, codepoint]) for planes/icons.py."""
import json
import os
import re
import urllib.request

from fontTools import subset

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "..", "planes", "fonts")
CDN = "https://cdn.jsdelivr.net/"

PACKS = {
    # Phosphor, fill weight (MIT): the house style
    "phosphor-fill": dict(
        ttf="npm/@phosphor-icons/web@2.1.2/src/fill/Phosphor-Fill.ttf",
        css="npm/@phosphor-icons/web@2.1.2/src/fill/style.css", prefix=r"ph-fill\.ph-",
        license="npm/@phosphor-icons/web@2.1.2/LICENSE",
        glyphs=dict(balloon="balloon", parachute="parachute", plane="airplane", sun="sun",
                    planet="planet", sparkle="star-four", dot="circle")),
    # Tabler, filled (MIT): Phosphor has no satellite
    "tabler-filled": dict(
        ttf="npm/@tabler/icons-webfont@3.48.0/dist/fonts/tabler-icons-filled.ttf",
        css="npm/@tabler/icons-webfont@3.48.0/dist/tabler-icons-filled.css", prefix=r"ti-",
        license="npm/@tabler/icons-webfont@3.48.0/LICENSE",
        glyphs=dict(satellite="satellite")),
    # Weather Icons (SIL OFL 1.1): the Moon in 28 phases
    "weather-icons": dict(
        ttf="gh/erikflowers/weather-icons@2.0.10/font/weathericons-regular-webfont.ttf",
        css="gh/erikflowers/weather-icons@2.0.10/css/weather-icons.css", prefix=r"wi-",
        license=None,  # the repo has no license file; its README says SIL OFL 1.1
        glyphs={"moon%d" % i: n for i, n in enumerate(
            ["moon-alt-new"] + ["moon-alt-waxing-crescent-%d" % k for k in range(1, 7)] + ["moon-alt-first-quarter"]
            + ["moon-alt-waxing-gibbous-%d" % k for k in range(1, 7)] + ["moon-alt-full"]
            + ["moon-alt-waning-gibbous-%d" % k for k in range(1, 7)] + ["moon-alt-third-quarter"]
            + ["moon-alt-waning-crescent-%d" % k for k in range(1, 7)])}),
}


def get(path):
    with urllib.request.urlopen(CDN + path) as r:
        return r.read()


table = {}
for name, pack in PACKS.items():
    css = get(pack["css"]).decode()
    codes = dict(re.findall(r"\." + pack["prefix"] + r"([a-z0-9-]+):+before\s*\{\s*content:\s*\"\\([0-9a-f]+)\"", css))
    picked = {icon: int(codes[glyph], 16) for icon, glyph in pack["glyphs"].items()}
    src = os.path.join(FONTS, name + ".full.ttf")
    with open(src, "wb") as f:
        f.write(get(pack["ttf"]))
    opts = subset.Options()
    opts.layout_features, opts.notdef_outline = [], True
    font = subset.load_font(src, opts)
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=picked.values())
    sub.subset(font)
    subset.save_font(font, os.path.join(FONTS, name + ".ttf"), opts)
    os.remove(src)
    with open(os.path.join(FONTS, name + "-LICENSE.txt"), "wb") as f:
        if pack["license"]:
            f.write(get(pack["license"]))
        else:
            # Same OFL text Inter ships with (fonts/LICENSE.txt), under Weather Icons' own notice
            with open(os.path.join(FONTS, "LICENSE.txt")) as lic:
                ofl = lic.read().split("\n", 2)[2]
            f.write(("Weather Icons by Erik Flowers (https://github.com/erikflowers/weather-icons)\n\n"
                     + ofl).encode())
    table.update({icon: [name + ".ttf", code] for icon, code in picked.items()})
    print(name, os.path.getsize(os.path.join(FONTS, name + ".ttf")), "bytes,", len(picked), "glyphs")

with open(os.path.join(FONTS, "icons.json"), "w") as f:
    json.dump(table, f, indent=1)
