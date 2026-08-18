#!/usr/bin/env python3
"""Fetch USGS 3DEP 1m DEM tiles intersecting an AOI, via the TNM Access API.

Usage: fetch_dem.py data/aoi/<name>.geojson
Writes tiles to data/raw/ and appends provenance to data/raw/MANIFEST.jsonl.
Idempotent: skips tiles already fully downloaded.
"""
import json, os, sys, urllib.request, urllib.parse, datetime

TNM = "https://tnmaccess.nationalmap.gov/api/v1/products"
DATASET = "Digital Elevation Model (DEM) 1 meter"

def bbox_of(geojson_path):
    gj = json.load(open(geojson_path))
    xs, ys = [], []
    def walk(c):
        if isinstance(c[0], (int, float)):
            xs.append(c[0]); ys.append(c[1])
        else:
            for k in c: walk(k)
    for f in gj["features"]:
        walk(f["geometry"]["coordinates"])
    return min(xs), min(ys), max(xs), max(ys)

def main(aoi_path):
    raw = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
    os.makedirs(raw, exist_ok=True)
    bbox = ",".join(str(v) for v in bbox_of(aoi_path))
    q = urllib.parse.urlencode({"datasets": DATASET, "bbox": bbox,
                                "outputFormat": "JSON", "max": "100"})
    items = json.load(urllib.request.urlopen(f"{TNM}?{q}"))["items"]
    print(f"{len(items)} tile(s) intersect {os.path.basename(aoi_path)}")
    for it in items:
        url = it["downloadURL"]
        dest = os.path.join(raw, os.path.basename(url))
        want = it.get("sizeInBytes") or 0
        if os.path.exists(dest) and (not want or os.path.getsize(dest) == want):
            print("  have", os.path.basename(dest)); continue
        print("  get ", os.path.basename(dest), f"({want/1e6:.0f} MB)")
        urllib.request.urlretrieve(url, dest + ".part")
        os.replace(dest + ".part", dest)
        with open(os.path.join(raw, "MANIFEST.jsonl"), "a") as m:
            m.write(json.dumps({"file": os.path.basename(dest), "source": url,
                "title": it["title"], "publicationDate": it.get("publicationDate"),
                "retrieved": datetime.date.today().isoformat()}) + "\n")

if __name__ == "__main__":
    main(sys.argv[1])
