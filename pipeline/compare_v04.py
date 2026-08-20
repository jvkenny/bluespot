#!/usr/bin/env python3
"""v0.3 (uniform C = 0.55) vs v0.4 (curve-number grid), citywide.

Produces the numbers behind the "v0.4 — spatially varying runoff" section of
docs/MODEL.md, and writes them to data/v04_comparison.json so the table in
the docs can be regenerated rather than retyped.

Two comparisons:

  1. Per bookmark: wet %, stored volume, max depth, and the mass-balance
     residual, old against new.
  2. Top-N pools by stored volume at a reference bookmark. The depression
     fill is identical between the two versions — v0.4 changes only how much
     water arrives — so a pool's FOOTPRINT is the same in both rasters and
     the honest comparison is: find the pool on the new raster, then sum the
     old raster over that same footprint. Pool ranks are reported for both.

Usage:
  compare_v04.py <old_dir> <new_dir> <out.json> [ref_sid] [top_n] [--names]

  <old_dir>  a directory holding chicago_scenarios.json + chicago_depth_*.tif
             (v0.3: <data_root>/citywide)
  <new_dir>  the same, for v0.4 (<data_root>/citywide_v04)
  --names    reverse-geocode pool labels from OSM Nominatim (1 req/s)
"""
import json, os, sys

import numpy as np
import rasterio
from rasterio.windows import Window, from_bounds
from rasterio.warp import transform as rio_transform
from scipy import ndimage

from pools import MAX_CELLS, MIN_AREA, PAD, POOL_MIN, revgeo


def scenario_table(old_dir, new_dir):
    o = {s["id"]: s for s in json.load(
        open(os.path.join(old_dir, "chicago_scenarios.json")))["scenarios"]}
    nj = json.load(open(os.path.join(new_dir, "chicago_scenarios.json")))
    rows = []
    for s in nj["scenarios"]:
        p = o.get(s["id"], {})
        rows.append({
            "id": s["id"], "rain_in": s["rain_in"], "label": s["label"],
            "old_wet_pct": p.get("wet_pct"), "new_wet_pct": s["wet_pct"],
            "old_stored_m3": p.get("stored_m3"), "new_stored_m3": s["stored_m3"],
            "old_max_depth_m": p.get("max_depth_m"),
            "new_max_depth_m": s["max_depth_m"],
            "old_net_mm": p.get("net_mm"), "new_net_mm_mean": s.get("net_mm_mean"),
            "old_balance_rel_err": p.get("balance_rel_err"),
            "new_balance_rel_err": s.get("balance_rel_err"),
            "wet_pct_delta": (round(s["wet_pct"] - p["wet_pct"], 2)
                              if p.get("wet_pct") is not None else None),
            "stored_pct_change": (
                round(100.0 * (s["stored_m3"] - p["stored_m3"]) / p["stored_m3"], 1)
                if p.get("stored_m3") else None)})
    return rows, nj.get("assumptions", {}), nj.get("balance_check", {})


def top_pools(new_path, old_path, top_n=10, names=False):
    """Top-N pools on the NEW raster, each also measured on the OLD one."""
    with rasterio.open(new_path) as new, rasterio.open(old_path) as old:
        decim = 1
        while (new.height * new.width) / decim ** 2 > MAX_CELLS:
            decim *= 2
        h, w = new.height // decim, new.width // decim
        d = new.read(1, out_shape=(h, w)).astype("float32")
        cell = abs(new.transform.a * decim) * abs(new.transform.e * decim)
        lab = np.zeros(d.shape, dtype="int32")
        n = ndimage.label(np.isfinite(d) & (d >= POOL_MIN),
                          structure=np.ones((3, 3)), output=lab)
        print(f"coarse pass {decim}x ({h}x{w}): {n:,} components", flush=True)
        objs = ndimage.find_objects(lab)
        vols = ndimage.sum_labels(np.where(lab > 0, d, 0), lab,
                                  index=np.arange(1, n + 1))
        counts = np.bincount(lab.ravel(), minlength=n + 1)[1:]
        cand = sorted(((float(vols[i]) * cell, i + 1, objs[i])
                       for i in range(n) if counts[i] * cell >= MIN_AREA),
                      key=lambda t: -t[0])[:2 * top_n]
        del d

        out = []
        for _, lid, sl in cand:
            r0 = max(sl[0].start * decim - PAD, 0)
            r1 = min(sl[0].stop * decim + PAD, new.height)
            c0 = max(sl[1].start * decim - PAD, 0)
            c1 = min(sl[1].stop * decim + PAD, new.width)
            win = Window(c0, r0, c1 - c0, r1 - r0)
            dn = new.read(1, window=win)
            tr = new.window_transform(win)
            a = abs(tr.a) * abs(tr.e)
            wl = np.zeros(dn.shape, dtype="int32")
            ndimage.label(np.isfinite(dn) & (dn >= POOL_MIN),
                          structure=np.ones((3, 3)), output=wl)
            rr, cc = np.nonzero(lab[sl] == lid)
            fr = np.clip(rr + sl[0].start, 0, None) * decim + decim // 2 - r0
            fc = np.clip(cc + sl[1].start, 0, None) * decim + decim // 2 - c0
            fr = np.clip(fr, 0, dn.shape[0] - 1); fc = np.clip(fc, 0, dn.shape[1] - 1)
            ids = np.unique(wl[fr, fc]); ids = ids[ids > 0]
            if ids.size == 0:
                continue
            sel = np.isin(wl, ids)
            if sel.sum() * a < MIN_AREA:
                continue
            # the same ground on the old raster, addressed by bounds rather
            # than by pixel offset in case the two mosaics differ in extent
            ow = from_bounds(*rasterio.transform.array_bounds(
                dn.shape[0], dn.shape[1], tr), old.transform
                             ).round_offsets().round_lengths()
            do = old.read(1, window=ow, boundless=True, fill_value=np.nan)
            if do.shape != dn.shape:
                do = np.full(dn.shape, np.nan, dtype="float32")
            k = np.unravel_index(np.argmax(np.where(sel, dn, -1)), dn.shape)
            x, y = rasterio.transform.xy(tr, *k)
            (lon,), (lat,) = rio_transform(new.crs, "EPSG:4326", [x], [y])
            out.append({
                "area_m2": int(round(float(sel.sum()) * a)),
                "new_volume_m3": int(round(float(np.nansum(dn[sel])) * a)),
                "old_volume_m3": int(round(float(np.nansum(do[sel])) * a)),
                "new_max_depth_m": round(float(dn[k]), 2),
                "old_max_depth_m": round(float(np.nanmax(np.where(sel, do, np.nan)))
                                         if np.isfinite(do[sel]).any() else 0.0, 2),
                "lon": round(lon, 6), "lat": round(lat, 6)})
            del dn, do, wl, sel
        out.sort(key=lambda p: -p["new_volume_m3"])
        out = out[:top_n]
        # old rank of the same footprints, among this same candidate set
        by_old = sorted(out, key=lambda p: -p["old_volume_m3"])
        for i, p in enumerate(out, 1):
            p["rank_new"] = i
        for i, p in enumerate(by_old, 1):
            p["rank_old_within_set"] = i
        for p in out:
            p["change_pct"] = (round(100.0 * (p["new_volume_m3"] - p["old_volume_m3"])
                                     / p["old_volume_m3"], 1)
                               if p["old_volume_m3"] else None)
            p["name"] = revgeo(p["lon"], p["lat"]) if names else ""
            if names:
                import time
                time.sleep(1.1)
        return out


def main(old_dir, new_dir, out_path, ref_sid="b75_100yr", top_n=10, names=False):
    top_n = int(top_n)
    rows, assumptions, balance = scenario_table(old_dir, new_dir)
    print(f"{'rung':>10} {'old wet%':>9} {'new wet%':>9} {'old m3':>14} "
          f"{'new m3':>14} {'change':>8}")
    for r in rows:
        print(f"{r['id']:>10} {str(r['old_wet_pct']):>9} {r['new_wet_pct']:>9} "
              f"{r['old_stored_m3']:>14,} {r['new_stored_m3']:>14,} "
              f"{str(r['stored_pct_change'])+'%':>8}")

    pools = top_pools(os.path.join(new_dir, f"chicago_depth_{ref_sid}.tif"),
                      os.path.join(old_dir, f"chicago_depth_{ref_sid}.tif"),
                      top_n, names)
    print(f"\ntop {len(pools)} pools at {ref_sid}")
    for p in pools:
        print(f"#{p['rank_new']:<2} {p['old_volume_m3']:>10,} -> "
              f"{p['new_volume_m3']:>10,} m3  {str(p['change_pct'])+'%':>8}  "
              f"{p['new_max_depth_m']:>5} m  {p['name']}")

    doc = {"generated_by": "pipeline/compare_v04.py",
           "old": {"dir": os.path.basename(old_dir.rstrip("/")),
                   "model": "v0.3 — uniform runoff coefficient C = 0.55"},
           "new": {"dir": os.path.basename(new_dir.rstrip("/")),
                   "model": "v0.4 — NRCS curve number per cell"},
           "assumptions_new": assumptions,
           "mass_balance_new": balance,
           "scenarios": rows,
           "top_pools": {"reference_scenario": ref_sid,
                         "note": "footprints come from the v0.4 raster; the "
                                 "v0.3 volume is that same footprint measured "
                                 "on the v0.3 raster. The depression fill is "
                                 "identical between versions, so this is the "
                                 "same physical pool in both columns.",
                         "pools": pools}}
    with open(out_path, "w") as f:
        json.dump(doc, f, indent=1)
    print(f"\n-> {out_path}")


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if x != "--names"]
    main(*a[:5], names="--names" in sys.argv)
