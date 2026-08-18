#!/usr/bin/env python3
"""Fetch open-water polygons (rivers, canals, lakes) for an AOI + buffer from
OpenStreetMap via Overpass, as GeoJSON. Water cells act as drainage outlets in
bluespot.py. (c) OpenStreetMap contributors, ODbL.

Usage: fetch_water.py data/aoi/<name>.geojson <buffer_deg> <out.geojson>
"""
import json, sys, urllib.request

def bbox_of(p, pad):
    gj = json.load(open(p)); xs, ys = [], []
    def walk(c):
        if isinstance(c[0], (int, float)): xs.append(c[0]); ys.append(c[1])
        else:
            for k in c: walk(k)
    for f in gj["features"]: walk(f["geometry"]["coordinates"])
    return min(ys)-pad, min(xs)-pad, max(ys)+pad, max(xs)+pad  # s,w,n,e

def main(aoi, pad, out):
    s, w, n, e = bbox_of(aoi, float(pad))
    q = f"""[out:json][timeout:90];
(way["natural"="water"]({s},{w},{n},{e});
 relation["natural"="water"]({s},{w},{n},{e});
 way["waterway"="riverbank"]({s},{w},{n},{e}););
out geom;"""
    req = urllib.request.Request("https://overpass-api.de/api/interpreter",
        data=q.encode(), headers={"User-Agent": "bluespot-pipeline/0.1"})
    els = json.load(urllib.request.urlopen(req))["elements"]
    feats = []
    for el in els:
        if el["type"] == "way" and "geometry" in el:
            ring = [[p["lon"], p["lat"]] for p in el["geometry"]]
            if len(ring) >= 4 and ring[0] == ring[-1]:
                feats.append({"type": "Feature", "properties": {"osm": el["id"]},
                    "geometry": {"type": "Polygon", "coordinates": [ring]}})
        elif el["type"] == "relation":
            for m in el.get("members", []):
                if m.get("role") == "outer" and "geometry" in m:
                    ring = [[p["lon"], p["lat"]] for p in m["geometry"]]
                    if len(ring) >= 4:
                        if ring[0] != ring[-1]: ring.append(ring[0])
                        feats.append({"type": "Feature",
                            "properties": {"osm": el["id"], "rel": True},
                            "geometry": {"type": "Polygon", "coordinates": [ring]}})
    json.dump({"type": "FeatureCollection", "features": feats}, open(out, "w"))
    print(f"{len(feats)} water polygons -> {out}")

if __name__ == "__main__":
    main(*sys.argv[1:4])
