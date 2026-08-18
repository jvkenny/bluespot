#!/usr/bin/env python3
"""Fetch open-water polygons (rivers, canals, lakes) for an AOI + buffer from
OpenStreetMap via Overpass, as GeoJSON. Water cells act as drainage outlets in
bluespot.py. (c) OpenStreetMap contributors, ODbL.

Handles multipolygon relations properly: member ways are stitched end-to-end
into closed rings (required for Lake Michigan, relation 1205149, whose outer
ring arrives as ~750 separate way segments), and inner rings become polygon
holes (required so islands — e.g. Goose Island inside the Chicago River —
do not become drainage outlets).

Usage: fetch_water.py data/aoi/<name>.geojson <buffer_deg> <out.geojson> [timeout_s]
"""
import json, sys, time, urllib.request

ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter"]

def bbox_of(p, pad):
    gj = json.load(open(p)); xs, ys = [], []
    def walk(c):
        if isinstance(c[0], (int, float)): xs.append(c[0]); ys.append(c[1])
        else:
            for k in c: walk(k)
    for f in gj["features"]: walk(f["geometry"]["coordinates"])
    return min(ys)-pad, min(xs)-pad, max(ys)+pad, max(xs)+pad  # s,w,n,e

def stitch(members):
    """Join way segments end-to-end into closed rings. Returns (rings, n_open)."""
    pool = [[(p["lon"], p["lat"]) for p in m["geometry"]]
            for m in members if "geometry" in m]
    rings, n_open = [], 0
    while pool:
        cur = pool.pop()
        while cur[0] != cur[-1]:
            for i, s in enumerate(pool):
                if s[0] == cur[-1]:   cur = cur + s[1:];        pool.pop(i); break
                if s[-1] == cur[-1]:  cur = cur + s[-2::-1];    pool.pop(i); break
                if s[0] == cur[0]:    cur = cur[::-1] + s[1:];  pool.pop(i); break
                if s[-1] == cur[0]:   cur = s + cur[1:];        pool.pop(i); break
            else:
                n_open += 1; cur = None; break
        if cur and len(cur) >= 4:
            rings.append([list(p) for p in cur])
    return rings, n_open

def contains(ring, pt):
    """Ray-cast point-in-ring test."""
    x, y = pt; inside = False
    for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) / (y1 - y0) * (x1 - x0):
            inside = not inside
    return inside

def relation_geom(el):
    """Assemble a relation's members into a MultiPolygon (holes assigned to
    the outer ring containing them)."""
    outers, no = stitch([m for m in el.get("members", []) if m.get("role") == "outer"])
    inners, ni = stitch([m for m in el.get("members", []) if m.get("role") == "inner"])
    if no or ni:
        print(f"  relation {el['id']}: dropped {no} open outer / {ni} open inner chains")
    if not outers:
        return None
    polys = [[o] for o in outers]
    for r in inners:
        for p in polys:
            if contains(p[0], r[0]):
                p.append(r); break
        else:
            max(polys, key=lambda p: len(p[0])).append(r)
    return {"type": "MultiPolygon", "coordinates": polys}

def main(aoi, pad, out, timeout=300):
    s, w, n, e = bbox_of(aoi, float(pad))
    q = f"""[out:json][timeout:{int(timeout)}];
(way["natural"="water"]({s},{w},{n},{e});
 relation["natural"="water"]({s},{w},{n},{e});
 way["waterway"="riverbank"]({s},{w},{n},{e}););
out geom;"""
    els = None
    for attempt in range(6):
        ep = ENDPOINTS[attempt % len(ENDPOINTS)]
        try:
            req = urllib.request.Request(ep, data=q.encode(),
                headers={"User-Agent": "bluespot-pipeline/0.1"})
            els = json.load(urllib.request.urlopen(req, timeout=int(timeout) + 60))["elements"]
            break
        except Exception as ex:
            print(f"  {ep}: {ex}; retrying...")
            time.sleep(15 * (attempt + 1))
    if els is None:
        sys.exit("Overpass failed on all endpoints/retries")
    feats = []
    for el in els:
        if el["type"] == "way" and "geometry" in el:
            ring = [[p["lon"], p["lat"]] for p in el["geometry"]]
            if len(ring) >= 4 and ring[0] == ring[-1]:
                feats.append({"type": "Feature", "properties": {"osm": el["id"]},
                    "geometry": {"type": "Polygon", "coordinates": [ring]}})
        elif el["type"] == "relation":
            g = relation_geom(el)
            if g:
                feats.append({"type": "Feature",
                    "properties": {"osm": el["id"], "rel": True,
                                   "name": el.get("tags", {}).get("name")},
                    "geometry": g})
    json.dump({"type": "FeatureCollection", "features": feats}, open(out, "w"))
    print(f"{len(feats)} water polygons -> {out}")

if __name__ == "__main__":
    main(*sys.argv[1:5])
