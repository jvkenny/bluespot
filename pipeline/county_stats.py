#!/usr/bin/env python3
"""Per-county zonal summary of a bluespot depth raster.

The regional product's headline is not one number, it is the spread between
counties, so this walks the depth COG in windows and accumulates, per county:
land cells carrying a valid depth value, cells wet at each depth band, and
total stored volume. Windowed because the regional raster is ~2e10 cells —
it never fits in RAM, and neither does a full-extent county id raster.

"Land cells" = cells with a finite depth value. Open water is nodata in the
product, and so is everything the DEM does not cover, so the denominator is
"land this product can actually see", not the county's legal area. Where
those differ (Will County's missing 3DEP coverage; Cook's and Lake's Lake
Michigan area) the difference is reported alongside, because a wet-% over an
unstated denominator is a misleading number.

Zones are the features of the given GeoJSON. They are normally the county
polygons, but any polygon file works — running it with the city boundary is
how the regional product is checked against the citywide one.

Usage: county_stats.py <depth.tif> <zones.geojson> <out.json> [win_px]
"""
import json, sys, time
import numpy as np
import rasterio
from rasterio.windows import Window
from rasterio.warp import transform_geom
from rasterio.features import rasterize

BANDS = [0.05, 0.15, 0.30, 1.00]     # m; report cells at or above each


def geom_bounds(g):
    xs, ys = [], []
    def walk(c):
        if isinstance(c[0], (int, float)): xs.append(c[0]); ys.append(c[1])
        else:
            for k in c: walk(k)
    walk(g["coordinates"])
    return min(xs), min(ys), max(xs), max(ys)


def main(depth_path, counties_path, out_path, win_px=4096):
    win_px = int(win_px)
    t0 = time.time()
    with rasterio.open(depth_path) as src:
        cell_m2 = abs(src.transform.a * src.transform.e)
        feats = json.load(open(counties_path))["features"]
        zones = []
        for i, f in enumerate(feats, 1):
            g = transform_geom("EPSG:4326", src.crs, f["geometry"])
            pr = f.get("properties") or {}
            zones.append({"id": i,
                          "name": pr.get("NAME") or pr.get("name") or f"zone{i}",
                          "geoid": pr.get("GEOID"),
                          "aland_km2": pr.get("ALAND", 0) / 1e6,
                          "awater_km2": pr.get("AWATER", 0) / 1e6,
                          "geom": g, "bbox": geom_bounds(g)})
        n = len(zones) + 1
        valid = np.zeros(n, dtype="int64")
        band = {b: np.zeros(n, dtype="int64") for b in BANDS}
        vol = np.zeros(n, dtype="float64")
        deepest = [None] * n

        nwin = 0
        for r0 in range(0, src.height, win_px):
            for c0 in range(0, src.width, win_px):
                w = Window(c0, r0, min(win_px, src.width - c0),
                           min(win_px, src.height - r0))
                d = src.read(1, window=w)
                fin = np.isfinite(d)
                if not fin.any():
                    continue
                nwin += 1
                tr = src.window_transform(w)
                wb = rasterio.windows.bounds(w, src.transform)
                shapes = [(z["geom"], z["id"]) for z in zones
                          if not (z["bbox"][2] < wb[0] or z["bbox"][0] > wb[2]
                                  or z["bbox"][3] < wb[1] or z["bbox"][1] > wb[3])]
                if not shapes:
                    continue
                zid = rasterize(shapes, out_shape=d.shape, transform=tr, fill=0,
                                dtype="int32")
                zid[~fin] = 0
                valid += np.bincount(zid.ravel(), minlength=n)
                valid[0] = 0
                dv = np.where(fin, d, 0).astype("float64")
                vol += np.bincount(zid.ravel(), weights=dv.ravel(), minlength=n)
                for b in BANDS:
                    m = zid * (dv >= b)
                    band[b] += np.bincount(m.ravel(), minlength=n)
                    band[b][0] = 0
                for z in zones:
                    sel = (zid == z["id"])
                    if not sel.any():
                        continue
                    k = np.unravel_index(np.argmax(np.where(sel, dv, -1)), d.shape)
                    dm = float(dv[k])
                    if deepest[z["id"]] is None or dm > deepest[z["id"]][0]:
                        deepest[z["id"]] = (dm, list(rasterio.transform.xy(tr, *k)))
                del d, fin, zid, dv

    rows = []
    for z in zones:
        i = z["id"]
        v = int(valid[i])
        rows.append({"county": z["name"], "geoid": z["geoid"],
            "aland_km2": round(z["aland_km2"], 1),
            "covered_km2": round(v * cell_m2 / 1e6, 1),
            "covered_pct_of_land": (round(100 * v * cell_m2 / 1e6 / z["aland_km2"], 1)
                                    if z["aland_km2"] else None),
            "land_cells": v,
            "wet_cells_5cm": int(band[0.05][i]),
            "wet_pct_5cm": round(100 * band[0.05][i] / max(v, 1), 2),
            "wet_pct_15cm": round(100 * band[0.15][i] / max(v, 1), 2),
            "wet_pct_30cm": round(100 * band[0.30][i] / max(v, 1), 2),
            "wet_pct_1m": round(100 * band[1.00][i] / max(v, 1), 2),
            "volume_m3": int(round(float(vol[i]) * cell_m2)),
            "max_depth_m": round(deepest[i][0], 2) if deepest[i] else None,
            "max_depth_xy": deepest[i][1] if deepest[i] else None})
    rows.sort(key=lambda r: -r["wet_pct_5cm"])
    tv = int(valid.sum()); tw = int(band[0.05].sum())
    total = {"land_cells": tv, "covered_km2": round(tv * cell_m2 / 1e6, 1),
             "wet_cells_5cm": tw, "wet_pct_5cm": round(100 * tw / max(tv, 1), 2),
             "volume_m3": int(round(float(vol.sum()) * cell_m2)),
             "windows_read": nwin, "secs": round(time.time() - t0)}
    json.dump({"raster": depth_path, "total": total, "counties": rows},
              open(out_path, "w"), indent=1)

    print(f"{'county':10s} {'land km2':>9s} {'cov%':>5s} {'wet% 5cm':>9s} "
          f"{'15cm':>6s} {'30cm':>6s} {'1m':>6s} {'max m':>7s}  volume Mm3")
    for r in rows:
        print(f"{r['county']:10s} {r['covered_km2']:9,.0f} "
              f"{(f"{r['covered_pct_of_land']:.0f}" if r['covered_pct_of_land'] else '-'):>5s} "
              f"{r['wet_pct_5cm']:9.2f} {r['wet_pct_15cm']:6.2f} {r['wet_pct_30cm']:6.2f} "
              f"{r['wet_pct_1m']:6.2f} {r['max_depth_m']:7.2f}  {r['volume_m3']/1e6:9.1f}")
    print(f"{'REGION':10s} {total['covered_km2']:9,.0f} {'':5s} "
          f"{total['wet_pct_5cm']:9.2f} {'':6s} {'':6s} {'':6s} {'':7s}  "
          f"{total['volume_m3']/1e6:9.1f}")
    print(f"-> {out_path} ({total['secs']}s, {nwin} windows)")


if __name__ == "__main__":
    main(*sys.argv[1:5])
