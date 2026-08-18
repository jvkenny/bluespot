#!/usr/bin/env python3
"""Region-scale open-water fetch from OpenStreetMap via Overpass.

fetch_water.py issues ONE bbox query, which is fine for a city but times out
(or gets throttled off) across the 7-county CMAP region. This version:

- splits the AOI bbox into a grid of sub-bboxes and queries each separately
- caches each chunk's raw Overpass response, so a rerun after a failure only
  refetches what is missing (Overpass is a shared free service — do not make
  it repeat work)
- rotates endpoints and backs off on failure
- merges everything and DEDUPES BY OSM ID. Deduping is not an optimisation:
  `out geom` returns a relation's full geometry for every sub-bbox it
  touches, so Lake Michigan (relation 1205149) comes back in full from each
  of the ~6 chunks along the shore.

Relation assembly (member-way stitching, inner rings as holes) is reused from
fetch_water.py — see that file and docs/METHOD.md for why it matters.

Usage:
  fetch_water_region.py <aoi.geojson> <buffer_deg> <out.geojson> \
      [nx] [ny] [cache_dir]
"""
import json, os, sys, time, urllib.request
from fetch_water import ENDPOINTS, bbox_of, relation_geom

TIMEOUT = 240          # s, Overpass-side query budget per chunk
MAX_ATTEMPTS = 6


def query(s, w, n, e, cache, tag):
    """One sub-bbox Overpass fetch, cached on disk by tag."""
    cp = os.path.join(cache, f"water_{tag}.json")
    if os.path.exists(cp) and os.path.getsize(cp) > 0:
        try:
            return json.load(open(cp))["elements"]
        except Exception:
            os.remove(cp)          # truncated cache entry, refetch
    q = f"""[out:json][timeout:{TIMEOUT}];
(way["natural"="water"]({s},{w},{n},{e});
 relation["natural"="water"]({s},{w},{n},{e});
 way["waterway"="riverbank"]({s},{w},{n},{e}););
out geom;"""
    for attempt in range(MAX_ATTEMPTS):
        ep = ENDPOINTS[attempt % len(ENDPOINTS)]
        try:
            req = urllib.request.Request(ep, data=q.encode(),
                headers={"User-Agent": "bluespot-pipeline/0.1"})
            body = urllib.request.urlopen(req, timeout=TIMEOUT + 120).read()
            data = json.loads(body)
            with open(cp, "wb") as f:
                f.write(body)
            return data["elements"]
        except Exception as ex:
            print(f"    {tag}: {ep}: {ex}; retry {attempt+1}/{MAX_ATTEMPTS}",
                  flush=True)
            time.sleep(20 * (attempt + 1))
    return None


def main(aoi, pad, out, nx=4, ny=4, cache=None):
    nx, ny = int(nx), int(ny)
    cache = cache or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "..", "data", "raw", "overpass")
    os.makedirs(cache, exist_ok=True)
    s0, w0, n0, e0 = bbox_of(aoi, float(pad))
    print(f"region bbox S{s0:.4f} W{w0:.4f} N{n0:.4f} E{e0:.4f} -> {nx}x{ny} chunks")

    ways, rels, failed = {}, {}, []
    for j in range(ny):
        for i in range(nx):
            s = s0 + (n0 - s0) * j / ny
            n = s0 + (n0 - s0) * (j + 1) / ny
            w = w0 + (e0 - w0) * i / nx
            e = w0 + (e0 - w0) * (i + 1) / nx
            tag = f"{i}_{j}"
            els = query(s, w, n, e, cache, tag)
            if els is None:
                print(f"  chunk {tag}: FAILED", flush=True); failed.append(tag); continue
            nw = nr = 0
            for el in els:
                if el["type"] == "way" and el["id"] not in ways:
                    ways[el["id"]] = el; nw += 1
                elif el["type"] == "relation" and el["id"] not in rels:
                    rels[el["id"]] = el; nr += 1
            print(f"  chunk {tag}: {len(els):6d} elements (+{nw} new ways, "
                  f"+{nr} new relations)", flush=True)
    if failed:
        sys.exit(f"chunks failed after retries: {failed} — rerun to resume")

    feats, n_open_ring = [], 0
    for el in ways.values():
        if "geometry" not in el:
            continue
        ring = [[p["lon"], p["lat"]] for p in el["geometry"]]
        if len(ring) >= 4 and ring[0] == ring[-1]:
            feats.append({"type": "Feature", "properties": {"osm": el["id"]},
                          "geometry": {"type": "Polygon", "coordinates": [ring]}})
        else:
            n_open_ring += 1
    for el in rels.values():
        g = relation_geom(el)
        if g:
            feats.append({"type": "Feature",
                          "properties": {"osm": el["id"], "rel": True,
                                         "name": el.get("tags", {}).get("name")},
                          "geometry": g})
    json.dump({"type": "FeatureCollection", "features": feats}, open(out, "w"))
    print(f"\n{len(ways)} unique ways ({n_open_ring} skipped: not closed rings), "
          f"{len(rels)} unique relations")
    print(f"{len(feats)} water polygons -> {out} "
          f"({os.path.getsize(out)/2**20:.1f} MB)")


if __name__ == "__main__":
    main(*sys.argv[1:7])
