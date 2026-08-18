#!/usr/bin/env python3
"""Extract the major ponding areas ("problem pools") from a bluespot depth
raster: connected regions of depth >= POOL_MIN, ranked by stored volume.
Outputs GeoJSON (EPSG:4326): pool outline polygons + a labeled point at each
pool's deepest cell, reverse-geocoded via Nominatim (OSM) for a working name.

Usage: pools.py <depth.tif> <out_prefix> [top_n]
Writes <out_prefix>_pools.geojson (polygons) and <out_prefix>_pool_labels.geojson
"""
import json, sys, time, urllib.request
import numpy as np
import rasterio
from rasterio import features
from rasterio.warp import transform_geom, transform as rio_transform
from skimage.measure import label

POOL_MIN = 0.15   # m: ignore nuisance-depth ponding when outlining problems
MIN_AREA = 400    # m^2: ignore tiny pockets

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

def main(depth_path, out_prefix, top_n=12):
    top_n = int(top_n)
    with rasterio.open(depth_path) as src:
        d = src.read(1); tr = src.transform; crs = src.crs
    mask = np.isfinite(d) & (d >= POOL_MIN)
    lab = label(mask, connectivity=2)
    ids, counts = np.unique(lab[lab > 0], return_counts=True)
    stats = []
    for i, n in zip(ids, counts):
        if n < MIN_AREA: continue
        sel = lab == i
        vol = float(d[sel].sum())
        k = np.unravel_index(np.argmax(np.where(sel, d, -1)), d.shape)
        stats.append({"id": int(i), "area_m2": int(n), "volume_m3": round(vol),
                      "max_depth_m": round(float(d[k]), 2), "rc": k})
    stats.sort(key=lambda s: -s["volume_m3"])
    stats = stats[:top_n]
    polys, pts = [], []
    for rank, s in enumerate(stats, 1):
        sel = (lab == s["id"]).astype("uint8")
        geoms = [g for g, v in features.shapes(sel, mask=sel.astype(bool),
                 transform=tr, connectivity=8) if v == 1]
        geoms = [transform_geom(crs, "EPSG:4326", g) for g in geoms]
        x, y = rasterio.transform.xy(tr, *s["rc"])
        (lon,), (lat,) = rio_transform(crs, "EPSG:4326", [x], [y])
        name = revgeo(lon, lat); time.sleep(1.1)
        props = {"rank": rank, "name": name, "area_m2": s["area_m2"],
                 "volume_m3": s["volume_m3"], "max_depth_m": s["max_depth_m"]}
        print(f"#{rank:<2} {s['max_depth_m']:>5} m  {s['area_m2']:>7,} m2  {name}")
        for g in geoms:
            polys.append({"type": "Feature", "properties": props, "geometry": g})
        pts.append({"type": "Feature", "properties": props,
                    "geometry": {"type": "Point", "coordinates": [lon, lat]}})
    json.dump({"type": "FeatureCollection", "features": polys},
              open(f"{out_prefix}_pools.geojson", "w"))
    json.dump({"type": "FeatureCollection", "features": pts},
              open(f"{out_prefix}_pool_labels.geojson", "w"))

if __name__ == "__main__":
    main(*sys.argv[1:])
