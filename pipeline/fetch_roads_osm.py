#!/usr/bin/env python3
"""Fetch the drivable OpenStreetMap road network over the Chicago AOI bbox.

Raw input for the Phase 2b passability work (intersect each rain rung's depth
raster with road centrelines). This script ONLY downloads and normalises
geometry — it builds no graph and computes no routing.

Per the data policy in AGENTS.md this is a large raw pull, so it lands on
Google Drive under `<data_root>/lifelines_raw/`, not in the repo:

    <data_root>/lifelines_raw/chicago_roads_osm.geojson
    <data_root>/lifelines_raw/cache/roads_<r>_<c>.json   per-chunk Overpass cache

Extent is the AOI *bounding box* plus a small pad, deliberately not clipped to
the city polygon: a severed street two blocks over the line still cuts access
into the city, and clipping is the analysis step's decision, not the fetch's.

Overpass is a free volunteer service. The AOI is split into a grid of
sub-bboxes, every chunk response is cached on disk, and a rerun after a
failure refetches only what is missing.

Usage: fetch_roads_osm.py [nx] [ny]      (default 5 5)

(c) OpenStreetMap contributors, ODbL.
"""
import datetime as _dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import paths                                          # noqa: E402
from lifelines_common import Clip, overpass           # noqa: E402

TODAY = _dt.date.today().isoformat()
PAD = 0.01
TIMEOUT = 600

# "Drivable" = the classes a car can legally use, including the alleys and
# parking aisles that `service` covers. Chicago's alley grid is unusually
# dense and floods in its own right, so it is fetched rather than filtered
# out here; downstream analysis can drop it.
CLASSES = ("motorway|trunk|primary|secondary|tertiary|unclassified|"
           "residential|living_street|service|"
           "motorway_link|trunk_link|primary_link|secondary_link|"
           "tertiary_link")

# Tags kept per way. bridge / tunnel / layer are not decoration: viaducts and
# underpasses are where Chicago's deepest pools already are, so a passability
# pass has to be able to tell a road deck over water from a road under one.
KEEP = ("highway", "name", "ref", "oneway", "bridge", "tunnel", "layer",
        "maxspeed", "access", "motor_vehicle", "lanes", "surface")


def chunk_query(s, w, n, e):
    return (f'[out:json][timeout:{TIMEOUT}];\n'
            f'way["highway"~"^({CLASSES})$"]({s},{w},{n},{e});\n'
            f'out geom;')


def main(nx=5, ny=5):
    nx, ny = int(nx), int(ny)
    clip = Clip()
    xs = [b[0] for b in clip.boxes] + [b[2] for b in clip.boxes]
    ys = [b[1] for b in clip.boxes] + [b[3] for b in clip.boxes]
    w0, s0, e0, n0 = min(xs) - PAD, min(ys) - PAD, max(xs) + PAD, max(ys) + PAD

    root = paths.data_root()
    out_dir = os.path.join(root, "lifelines_raw")
    cache = os.path.join(out_dir, "cache")
    os.makedirs(cache, exist_ok=True)
    out_path = os.path.join(out_dir, "chicago_roads_osm.geojson")
    if os.path.exists(out_path):
        sys.exit(f"{out_path} already exists — refusing to overwrite. "
                 "Delete it deliberately if you mean to refetch.")

    dw, dn = (e0 - w0) / nx, (n0 - s0) / ny
    seen = set()
    n_feat = 0
    hist = {}
    with open(out_path, "w") as fh:
        fh.write('{"type":"FeatureCollection",\n')
        fh.write(f'"name":"chicago_roads_osm","retrieved":"{TODAY}",\n')
        fh.write('"source":"openstreetmap",'
                 '"license":"ODbL 1.0, (c) OpenStreetMap contributors",\n')
        fh.write(f'"bbox":[{w0:.5f},{s0:.5f},{e0:.5f},{n0:.5f}],\n')
        fh.write('"features":[\n')
        first = True
        for r in range(ny):
            for c in range(nx):
                s = s0 + r * dn
                n = s + dn
                w = w0 + c * dw
                e = w + dw
                cp = os.path.join(cache, f"roads_{r}_{c}.json")
                if os.path.exists(cp) and os.path.getsize(cp) > 0:
                    try:
                        els = json.load(open(cp))["elements"]
                    except Exception:                 # truncated cache entry
                        os.remove(cp)
                        els = None
                else:
                    els = None
                if els is None:
                    print(f"chunk {r},{c} ({s:.3f},{w:.3f})-({n:.3f},{e:.3f})")
                    els = overpass(chunk_query(s, w, n, e), timeout=TIMEOUT)
                    with open(cp, "w") as ch:
                        json.dump({"elements": els}, ch)
                kept = 0
                for el in els:
                    if el["id"] in seen or "geometry" not in el:
                        continue
                    seen.add(el["id"])
                    coords = [[round(p["lon"], 6), round(p["lat"], 6)]
                              for p in el["geometry"]]
                    if len(coords) < 2:
                        continue
                    tags = el.get("tags", {})
                    props = {"osm_id": el["id"]}
                    props.update({k: tags[k] for k in KEEP if k in tags})
                    hist[tags.get("highway")] = hist.get(
                        tags.get("highway"), 0) + 1
                    feat = {"type": "Feature", "properties": props,
                            "geometry": {"type": "LineString",
                                         "coordinates": coords}}
                    fh.write(("" if first else ",\n") + json.dumps(feat))
                    first = False
                    kept += 1
                    n_feat += 1
                print(f"  chunk {r},{c}: {len(els)} ways, {kept} new "
                      f"(running total {n_feat})")
        fh.write("\n]}\n")

    mb = os.path.getsize(out_path) / 1e6
    print(f"\n{n_feat} ways, {mb:.1f} MB -> {out_path}")
    print("by highway class:")
    for k, v in sorted(hist.items(), key=lambda kv: -kv[1]):
        print(f"  {k:18s} {v}")
    summary = {"retrieved": TODAY, "ways": n_feat, "size_mb": round(mb, 1),
               "bbox": [w0, s0, e0, n0], "by_highway": hist,
               "source": "openstreetmap", "license": "ODbL 1.0"}
    with open(os.path.join(out_dir, "chicago_roads_osm.summary.json"),
              "w") as fh:
        json.dump(summary, fh, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:3])
