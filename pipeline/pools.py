#!/usr/bin/env python3
"""Extract the major ponding areas ("problem pools") from a bluespot depth
raster: connected regions of depth >= POOL_MIN, ranked by stored volume.
Outputs GeoJSON (EPSG:4326): pool outline polygons + a labeled point at each
pool's deepest cell, reverse-geocoded via Nominatim (OSM) for a working name
(1 req/s, top-N only).

Scales to citywide rasters: if the raster exceeds ~400M cells, connected
components are found on a decimated read (nearest-neighbour), then each
candidate pool is re-read at full 1 m resolution in its own window for exact
area / volume / max depth / outline. Candidate ranking happens on the coarse
pass; 2x top_n candidates are refined so coarse-vs-exact rank swaps near the
cutoff don't drop a real top-N pool.

If a boundary GeoJSON (e.g. the city limits) is given, each pool gets an
"edge_truncated" property: true when the pool touches the boundary, meaning
its area/volume are fragments of a larger real-world feature that continues
outside the product (see docs/METHOD.md).

Usage: pools.py <depth.tif> <out_prefix> [top_n] [boundary.geojson]
Writes <out_prefix>_pools.geojson (polygons) and <out_prefix>_pool_labels.geojson
"""
import json, sys, time, urllib.request
import numpy as np
import rasterio
from rasterio import features
from rasterio.windows import Window
from rasterio.warp import transform_geom, transform as rio_transform
from scipy import ndimage

POOL_MIN = 0.15    # m: ignore nuisance-depth ponding when outlining problems
MIN_AREA = 400     # m^2: ignore tiny pockets
MAX_CELLS = 4e8    # decimate the labeling pass above this raster size
PAD = 256          # px: refinement window padding around a coarse pool bbox

def revgeo(lon, lat):
    url = (f"https://nominatim.openstreetmap.org/reverse?lon={lon}&lat={lat}"
           "&format=jsonv2&zoom=17")
    req = urllib.request.Request(url, headers={"User-Agent": "bluespot-pipeline/0.1"})
    try:
        a = json.load(urllib.request.urlopen(req)).get("address", {})
        road = a.get("road", "")
        hood = a.get("neighbourhood") or a.get("suburb") or ""
        return ", ".join(x for x in (road, hood) if x) or "unnamed"
    except Exception:
        return "unnamed"

SIMPLIFY_TOL = 1.25  # m: Douglas-Peucker on pool outlines (pixel-perimeter
                     # polygons are ~20x heavier than the map needs)

def simplify(geom):
    from skimage.measure import approximate_polygon
    out = []
    for ring in geom["coordinates"]:
        r = approximate_polygon(np.array(ring), tolerance=SIMPLIFY_TOL)
        if len(r) >= 4:
            out.append(r.tolist())
    return {"type": "Polygon", "coordinates": out or geom["coordinates"]}

def boundary_lines(boundary_path, crs):
    """City-limit polygon rings as LineStrings in the raster CRS."""
    if not boundary_path:
        return []
    lines = []
    for f in json.load(open(boundary_path))["features"]:
        g = transform_geom("EPSG:4326", crs, f["geometry"])
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for p in polys:
            for ring in p:
                lines.append({"type": "LineString", "coordinates": ring})
    return lines

def coarse_pools(src, decim):
    """Label connected pools on a decimated read; return candidate stats."""
    h, w = src.height // decim, src.width // decim
    d = src.read(1, out_shape=(h, w)).astype("float32")   # nearest resampling
    cell = abs(src.transform.a * decim) * abs(src.transform.e * decim)
    mask = np.isfinite(d) & (d >= POOL_MIN)
    lab = np.zeros(d.shape, dtype="int32")
    n = ndimage.label(mask, structure=np.ones((3, 3)), output=lab)
    del mask
    print(f"coarse pass: {decim}x decimated ({h}x{w}), {n} components")
    objs = ndimage.find_objects(lab)
    vols = ndimage.sum_labels(np.where(lab > 0, d, 0), lab, index=np.arange(1, n + 1))
    counts = np.bincount(lab.ravel())[1:]
    stats = []
    for i in range(n):
        if counts[i] * cell < MIN_AREA:
            continue
        stats.append({"id": i + 1, "vol": float(vols[i]) * cell, "slice": objs[i]})
    stats.sort(key=lambda s: -s["vol"])
    return stats, lab

def refine(src, sl, decim, lab, lab_id, blines):
    """Re-read one candidate pool at full res; exact stats + outline."""
    r0 = max(sl[0].start * decim - PAD, 0); r1 = min(sl[0].stop * decim + PAD, src.height)
    c0 = max(sl[1].start * decim - PAD, 0); c1 = min(sl[1].stop * decim + PAD, src.width)
    win = Window(c0, r0, c1 - c0, r1 - r0)
    d = src.read(1, window=win)
    tr = src.window_transform(win)
    cell = abs(tr.a) * abs(tr.e)
    mask = np.isfinite(d) & (d >= POOL_MIN)
    wl = np.zeros(d.shape, dtype="int32")
    ndimage.label(mask, structure=np.ones((3, 3)), output=wl)
    # which full-res components belong to this coarse pool? sample its cells
    rr, cc = np.nonzero(lab[sl] == lab_id)
    rr = rr + sl[0].start; cc = cc + sl[1].start          # coarse coords
    fr = np.clip(rr * decim + decim // 2 - r0, 0, d.shape[0] - 1)
    fc = np.clip(cc * decim + decim // 2 - c0, 0, d.shape[1] - 1)
    ids = np.unique(wl[fr, fc]); ids = ids[ids > 0]
    if ids.size == 0:
        return None
    sel = np.isin(wl, ids)
    area = float(sel.sum()) * cell
    if area < MIN_AREA:
        return None
    vol = float(d[sel].sum()) * cell
    k = np.unravel_index(np.argmax(np.where(sel, d, -1)), d.shape)
    edge = False
    if blines:
        bl = features.rasterize(blines, out_shape=d.shape, transform=tr,
                                fill=0, default_value=1, dtype="uint8").astype(bool)
        edge = bool((ndimage.binary_dilation(sel, np.ones((3, 3))) & bl).any())
    geoms = [g for g, v in features.shapes(sel.astype("uint8"), mask=sel,
             transform=tr, connectivity=8) if v == 1]
    geoms = [simplify(g) for g in geoms]
    return {"area_m2": int(round(area)), "volume_m3": int(round(vol)),
            "max_depth_m": round(float(d[k]), 2), "edge_truncated": edge,
            "rc": (k[0] + r0, k[1] + c0), "geoms": geoms, "tr": tr}

def main(depth_path, out_prefix, top_n=12, boundary=None):
    top_n = int(top_n)
    with rasterio.open(depth_path) as src:
        crs = src.crs
        blines = boundary_lines(boundary, crs)
        ncells = src.height * src.width
        decim = 1
        while ncells / decim ** 2 > MAX_CELLS:
            decim *= 2
        stats, lab = coarse_pools(src, decim)
        print(f"{len(stats)} candidate pools >= {MIN_AREA} m2; refining top {2*top_n}")
        refined = []
        for s in stats[:2 * top_n]:
            r = refine(src, s["slice"], decim, lab, s["id"], blines)
            if r: refined.append(r)
        refined.sort(key=lambda r: -r["volume_m3"])
        refined = refined[:top_n]
        polys, pts = [], []
        for rank, s in enumerate(refined, 1):
            geoms = [transform_geom(crs, "EPSG:4326", g) for g in s["geoms"]]
            x, y = rasterio.transform.xy(src.transform, *s["rc"])
            (lon,), (lat,) = rio_transform(crs, "EPSG:4326", [x], [y])
            name = revgeo(lon, lat); time.sleep(1.1)
            props = {"rank": rank, "name": name, "area_m2": s["area_m2"],
                     "volume_m3": s["volume_m3"], "max_depth_m": s["max_depth_m"],
                     "edge_truncated": s["edge_truncated"]}
            print(f"#{rank:<2} {s['max_depth_m']:>5} m  {s['area_m2']:>8,} m2  "
                  f"{s['volume_m3']:>8,} m3 {'EDGE' if s['edge_truncated'] else '    '} {name}")
            for g in geoms:
                polys.append({"type": "Feature", "properties": props, "geometry": g})
            pts.append({"type": "Feature", "properties": props,
                        "geometry": {"type": "Point", "coordinates": [lon, lat]}})
    json.dump({"type": "FeatureCollection", "features": polys},
              open(f"{out_prefix}_pools.geojson", "w"))
    json.dump({"type": "FeatureCollection", "features": pts},
              open(f"{out_prefix}_pool_labels.geojson", "w"))
    total_vol = sum(s["volume_m3"] for s in refined)
    print(f"top {len(refined)} pools, total volume {total_vol:,} m3")

if __name__ == "__main__":
    main(*sys.argv[1:5])
