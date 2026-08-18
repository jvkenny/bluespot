#!/usr/bin/env python3
"""Fetch USGS 3DEP 1m DEM tiles intersecting an AOI, via the TNM Access API.

Usage: fetch_dem.py data/aoi/<name>.geojson [project_substring]
Writes tiles to <data_root>/dem/ (Google Drive by default; see paths.py)
and appends provenance to MANIFEST.jsonl there.
Idempotent: skips tiles already fully downloaded.

Where multiple lidar projects overlap an AOI, pass a project_substring
(e.g. "IL_4_County") to pin one vintage — mixing projects creates seams
at acquisition boundaries.
"""
import json, os, sys, urllib.request, urllib.parse, datetime
from paths import data_root

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

def main(aoi_path, project=None):
    raw = os.path.join(data_root(), "dem")
    os.makedirs(raw, exist_ok=True)
    bbox = ",".join(str(v) for v in bbox_of(aoi_path))
    q = urllib.parse.urlencode({"datasets": DATASET, "bbox": bbox,
                                "outputFormat": "JSON", "max": "100"})
    items = json.load(urllib.request.urlopen(f"{TNM}?{q}"))["items"]
    if project:
        items = [it for it in items if project in it["title"]]
    print(f"{len(items)} tile(s) intersect {os.path.basename(aoi_path)}"
          + (f" (project filter: {project})" if project else ""))
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
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
