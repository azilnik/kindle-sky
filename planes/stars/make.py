"""Build stars.json (the bright stars and their names) from d3-celestial's data (BSD-3,
LICENSE beside this).
Run on the Mac: python3 planes/stars/make.py. The Kindle only ever reads the output."""
import json
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "https://cdn.jsdelivr.net/npm/d3-celestial@0.7.35/data/"
MAG_LIMIT = 2.5      # the faintest the sky frame draws (sky.mag_limit): the shapes people know
NAME_LIMIT = 1.0     # only the stars people know by name get one
ALSO_NAMED = {"Polaris"}


def get(name):
    with urllib.request.urlopen(BASE + name) as r:
        return json.load(r)


def ra_dec(c):
    return [round(c[0] % 360, 3), round(c[1], 3)]


stars = get("stars.6.json")["features"]
names = get("starnames.json")

out = {
    "stars": [ra_dec(f["geometry"]["coordinates"]) + [f["properties"]["mag"]]
              for f in stars if f["properties"]["mag"] <= MAG_LIMIT],
    "names": [ra_dec(f["geometry"]["coordinates"]) + [names[str(f["id"])]["name"]]
              for f in stars if names.get(str(f["id"]), {}).get("name")
              and (f["properties"]["mag"] <= NAME_LIMIT or names[str(f["id"])]["name"] in ALSO_NAMED)],
}
with open(os.path.join(HERE, "stars.json"), "w") as f:
    json.dump(out, f, separators=(",", ":"))
print({k: len(v) for k, v in out.items()}, os.path.getsize(os.path.join(HERE, "stars.json")), "bytes")
