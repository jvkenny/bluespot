#!/usr/bin/env python3
"""NRCS Curve Number grid (docs/MODEL.md v0.4).

Builds a per-cell runoff curve number from two public inputs — NLCD 2021 land
cover + percent developed imperviousness (MRLC) and SSURGO hydrologic soil
group (USDA-NRCS) — and delivers it on exactly the DEM's grid so the scenario
model can index it cell for cell.

Two stages, both idempotent:

  cn.py grid  <aoi.geojson> <name>
      -> <data_root>/cn/cn30_<name>.tif   (uint8 CN, 30 m, EPSG:5070,
                                           on the NLCD grid, no resampling)
      -> <data_root>/cn/cn30_<name>.json  (build record + QA histograms)

  cn.py tiles <name> <dem_dir> <aoi.geojson>
      -> <data_root>/cn/tiles_<name>/cn_<demtile>.tif
      One CN raster per DEM tile, with that tile's CRS, transform and shape
      copied verbatim, so a scenario chunk reads the same window from the CN
      VRT that it reads from the DEM VRT and the arrays line up by index.

Why CN, and what it replaces: v0.2/v0.3 turned rain into runoff with one
uniform coefficient C = 0.55 everywhere. The curve number method (NRCS, in
service since the 1950s) makes runoff depend on land cover and soil, and is
nonlinear in rain depth — small storms run off far less than C·R implies,
large ones somewhat more. See `runoff_in` below and docs/MODEL.md.

    S = 1000/CN - 10          (inches of potential maximum retention)
    Ia = 0.2 S                (initial abstraction)
    Q = (P - Ia)^2 / (P + 0.8 S)   for P > Ia, else 0

CURVE NUMBER SOURCES AND THE ASSIGNMENT WE MADE
-----------------------------------------------
The CN values below are USDA-NRCS TR-55 (2nd ed., June 1986) Tables 2-2a to
2-2c, reprinted as NEH Part 630 Chapter 9 (data/SOURCES.md #12). NRCS does
not publish an NLCD crosswalk, so **the assignment of each NLCD class to a
TR-55 cover description is ours** and is written out class by class in
`CN_TABLE` — every row names the TR-55 cover it borrows, so any disagreement
is with one line, not with a black box.

Three assignment choices are worth arguing with:

  * All four Developed classes take the same pervious CN — "open space, good
    condition" — and get their intensity entirely from the measured
    imperviousness raster. That is not laziness: TR-55's own composite-CN
    chart (Figure 2-3) is built on open space in good condition as the
    pervious cover, and the NLCD Developed classes are *defined* by
    imperviousness bins, so taking both the class and the percentage would
    count the same pavement twice.
  * Wetlands (90, 95) are given CN 98 for every soil group. TR-55 has no
    wetland row. Saturated ground has no available retention, so it behaves
    like an impervious surface for the storm's purposes. This is OUR rule,
    not NRCS's, and it is the most conservative reading; wetlands are 3.0% of
    the city land area (see the build JSON), and most of them sit inside
    depressions that are already pools in this model.
  * Open water (11) and ice (12) are CN 98 as well. In practice those cells
    are usually masked as open water by the scenario model anyway.

DUAL HYDROLOGIC SOIL GROUPS
---------------------------
SSURGO reports A/D, B/D and C/D for soils whose group depends on drainage:
the first letter applies where the soil has been artificially drained, D
where it has not (NEH Part 630 Ch. 7). We assume **undrained — dual classes
become D** — because the drainage state of any given parcel is not public
data, and D is both the standard default and the conservative one. In the
Chicago AOI dual classes are a large minority of map units, so this is a real
assumption, not a corner case; the build JSON records how much land it
touches.

MAP UNITS WITH NO HYDROLOGIC SOIL GROUP
---------------------------------------
Some SSURGO map units have no group at all — "Urban land", "Made land",
"Pits", "Water" are miscellaneous areas, not soils, and NRCS assigns them
nothing. That is common under a city core. Those cells, and any ground
SSURGO has not mapped, are filled with the group of the **nearest cell that
does have one** (Euclidean, on the 30 m grid). Borrowing the neighbouring
soil is standard practice and is the right shape of answer here: what is
under the pavement is the same glacial till as next door, and the pavement
itself is already accounted for by the imperviousness raster. The build JSON
records the filled fraction and the distance distribution.
"""
import json, os, sys, time
from collections import Counter

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.warp import Resampling, reproject, transform_geom

from paths import data_root

# hydrologic soil group codes used in the intermediate rasters
HSG_CODES = {"A": 1, "B": 2, "C": 3, "D": 4}
# undrained assumption: the dual classes collapse onto D
HSG_DUAL = {"A/D": 4, "B/D": 4, "C/D": 4}
HSG_NAMES = {1: "A", 2: "B", 3: "C", 4: "D"}

CN_IMPERVIOUS = 98    # TR-55 Table 2-2a, "impervious areas: paved parking
                      # lots, roofs, driveways"; also paved streets with
                      # curbs and storm sewers
CN_MIN, CN_MAX = 30, 100

# NLCD class -> (name, TR-55 cover description borrowed, (CN_A, CN_B, CN_C, CN_D))
CN_TABLE = {
    11: ("Open Water", "open water (our rule: CN 98)", (98, 98, 98, 98)),
    12: ("Perennial Ice/Snow", "open water (our rule: CN 98)", (98, 98, 98, 98)),
    21: ("Developed, Open Space", "urban open space, good condition (>75% grass)", (39, 61, 74, 80)),
    22: ("Developed, Low Intensity", "urban open space, good condition (>75% grass)", (39, 61, 74, 80)),
    23: ("Developed, Medium Intensity", "urban open space, good condition (>75% grass)", (39, 61, 74, 80)),
    24: ("Developed, High Intensity", "urban open space, good condition (>75% grass)", (39, 61, 74, 80)),
    31: ("Barren Land", "newly graded area, pervious only, no vegetation", (77, 86, 91, 94)),
    41: ("Deciduous Forest", "woods, good condition", (30, 55, 70, 77)),
    42: ("Evergreen Forest", "woods, good condition", (30, 55, 70, 77)),
    43: ("Mixed Forest", "woods, good condition", (30, 55, 70, 77)),
    51: ("Dwarf Scrub", "brush-weed-grass mixture, fair condition", (35, 56, 70, 77)),
    52: ("Shrub/Scrub", "brush-weed-grass mixture, fair condition", (35, 56, 70, 77)),
    71: ("Grassland/Herbaceous", "pasture, grassland or range, good condition", (39, 61, 74, 80)),
    72: ("Sedge/Herbaceous", "pasture, grassland or range, good condition", (39, 61, 74, 80)),
    73: ("Lichens", "pasture, grassland or range, good condition", (39, 61, 74, 80)),
    74: ("Moss", "pasture, grassland or range, good condition", (39, 61, 74, 80)),
    81: ("Pasture/Hay", "pasture, grassland or range, good condition", (39, 61, 74, 80)),
    82: ("Cultivated Crops", "row crops, straight row, good condition", (67, 78, 85, 89)),
    90: ("Woody Wetlands", "saturated ground (our rule: CN 98)", (98, 98, 98, 98)),
    95: ("Emergent Herbaceous Wetlands", "saturated ground (our rule: CN 98)", (98, 98, 98, 98)),
}

# Cells the CN grid cannot reach (outside the NLCD/SSURGO subset). Should be
# zero inside any AOI the inputs were fetched for; scenario.py counts them and
# says so out loud rather than silently treating them as zero runoff.
CN_FALLBACK = 74      # HSG C under urban open space in good condition


# ------------------------------------------------------------- the method --
def runoff_in(cn, rain_in):
    """NRCS runoff depth (inches) for curve number(s) `cn` and rain `rain_in`.

    Q = (P - 0.2 S)^2 / (P + 0.8 S) for P > 0.2 S, else 0, S = 1000/CN - 10.
    Vectorised over `cn`; `rain_in` is a scalar."""
    cn = np.asarray(cn, dtype=np.float64)
    S = np.where(cn > 0, 1000.0 / np.maximum(cn, 1e-9) - 10.0, np.inf)
    Ia = 0.2 * S
    q = np.zeros_like(S)
    m = (rain_in > Ia) & np.isfinite(S)
    q[m] = (rain_in - Ia[m]) ** 2 / (rain_in + 0.8 * S[m])
    return q


def runoff_mm_by_cn(rain_in, cn_max=CN_MAX):
    """Lookup table: runoff in mm for every integer CN 0..cn_max.

    Index 0 (no CN) yields the CN_FALLBACK runoff, so a hole in the CN grid
    behaves like ordinary urban ground rather than like a dry hole."""
    lut = runoff_in(np.arange(cn_max + 1), rain_in) * 25.4
    lut[0] = runoff_in(CN_FALLBACK, rain_in) * 25.4
    return lut


# ------------------------------------------------------------ stage 1: 30m --
def _hsg_raster(mapunit_path, hydgrp_path, shape, transform, crs, log=print):
    """Rasterize SSURGO map units to HSG codes on the NLCD grid, then fill
    the unmapped/miscellaneous-area holes from the nearest mapped cell.

    The map units arrive from SDA in EPSG:4326 and the NLCD grid is
    EPSG:5070, so every geometry is reprojected before it is burned."""
    table = json.load(open(hydgrp_path))["hydgrp"]
    feats = json.load(open(mapunit_path))["features"]
    shapes, duals, seen = [], [], Counter()
    for f in feats:
        rec = table.get(f["properties"]["mukey"])
        g = rec["hydgrp"] if rec else None
        if not g:
            seen["<none>"] += 1
            continue
        code = HSG_CODES.get(g) or HSG_DUAL.get(g)
        if not code:
            seen[f"<unknown:{g}>"] += 1
            continue
        seen[g] += 1
        geom = transform_geom("EPSG:4326", crs, f["geometry"])
        shapes.append((geom, code))
        if g in HSG_DUAL:
            duals.append((geom, 1))
    log("  map-unit polygons by group: " +
        " ".join(f"{k}:{v}" for k, v in sorted(seen.items())))
    # rasterize in a deterministic order (later shapes win on overlap)
    shapes.sort(key=lambda s: s[1])
    hsg = rasterize(shapes, out_shape=shape, transform=transform, fill=0,
                    dtype="uint8", all_touched=False)
    dual = rasterize(duals, out_shape=shape, transform=transform, fill=0,
                     dtype="uint8").astype(bool) if duals else \
        np.zeros(shape, dtype=bool)
    gap = hsg == 0
    dist = None
    if gap.any() and not gap.all():
        from scipy import ndimage
        dist, idx = ndimage.distance_transform_edt(gap, return_indices=True)
        hsg = hsg[tuple(idx)]
        dual = dual[tuple(idx)]
    return hsg, dual, gap, dist, {"mapunit_polygons_by_group":
                                  dict(sorted(seen.items()))}


def build_grid(aoi_path, name, force=False, log=print):
    root = data_root()
    lc_dir, soil_dir = os.path.join(root, "landcover"), os.path.join(root, "soils")
    cn_dir = os.path.join(root, "cn")
    os.makedirs(cn_dir, exist_ok=True)
    out = os.path.join(cn_dir, f"cn30_{name}.tif")
    out_json = os.path.join(cn_dir, f"cn30_{name}.json")
    if os.path.exists(out) and os.path.exists(out_json) and not force:
        log(f"{out}: exists, kept")
        return out

    t0 = time.time()
    lc_path = os.path.join(lc_dir, f"nlcd2021_landcover_{name}.tif")
    imp_path = os.path.join(lc_dir, f"nlcd2021_impervious_{name}.tif")
    mu_path = os.path.join(soil_dir, f"ssurgo_mapunitpoly_{name}.geojson")
    hg_path = os.path.join(soil_dir, f"ssurgo_hydgrp_{name}.json")
    for p in (lc_path, imp_path, mu_path, hg_path):
        if not os.path.exists(p):
            sys.exit(f"missing input {p} — run fetch_cn_inputs.py first")

    with rasterio.open(lc_path) as s:
        lc = s.read(1)
        profile, transform, crs = s.profile, s.transform, s.crs
    with rasterio.open(imp_path) as s:
        imp = s.read(1)
        if (s.height, s.width) != lc.shape or s.transform != transform:
            sys.exit("land cover and imperviousness are not on the same grid")
    log(f"NLCD grid {lc.shape[1]}x{lc.shape[0]} @ 30 m, {crs}")

    hsg, dual, gap, dist, hsg_stats = _hsg_raster(
        mu_path, hg_path, lc.shape, transform, crs, log=log)

    # QA denominators that mean something: the AOI polygon, minus open water.
    # Over a lake-fronting AOI the raw "% of the subset with no soil group" is
    # dominated by Lake Michigan and by margin outside the survey areas.
    from bluespot import load_geoms
    aoi = rasterize(load_geoms(aoi_path, crs), out_shape=lc.shape,
                    transform=transform, fill=0, default_value=1,
                    dtype="uint8").astype(bool)
    land = aoi & (lc != 11) & (lc != 0)
    nland = max(int(land.sum()), 1)
    hsg_stats.update({
        "qa_denominator": "cells inside the AOI polygon that are neither "
                          "open water (NLCD 11) nor land-cover nodata",
        "aoi_land_cells_30m": nland,
        "hsg_gap_fraction_all": round(float(gap.mean()), 6),
        "hsg_gap_fraction_aoi_land": round(float(gap[land].mean()), 6),
        "hsg_dual_fraction_aoi_land": round(float(dual[land].mean()), 6),
        "hsg_fill_median_m_aoi_land": round(
            float(np.median(dist[land & gap])) * 30.0, 1)
        if dist is not None and (land & gap).any() else 0.0,
        "hsg_fill_max_m_aoi_land": round(
            float(dist[land & gap].max()) * 30.0, 1)
        if dist is not None and (land & gap).any() else 0.0,
    })
    log(f"  soil group missing on {100*hsg_stats['hsg_gap_fraction_aoi_land']:.2f}% "
        f"of AOI land (filled from nearest mapped cell, median "
        f"{hsg_stats['hsg_fill_median_m_aoi_land']:.0f} m, max "
        f"{hsg_stats['hsg_fill_max_m_aoi_land']:.0f} m) | dual A/D,B/D,C/D "
        f"-> D on {100*hsg_stats['hsg_dual_fraction_aoi_land']:.1f}% of AOI land")
    del gap, dist, dual

    # pervious CN from the NLCD class x soil group table
    lut = np.zeros((256, 5), dtype=np.uint8)      # [class, hsg 0..4]
    for k, (_, _, cns) in CN_TABLE.items():
        lut[k, 1:] = cns
        lut[k, 0] = cns[2]                        # unreachable: HSG is filled
    unknown = sorted(set(np.unique(lc).tolist()) - set(CN_TABLE) - {0})
    if unknown:
        log(f"  warning: NLCD classes with no CN row, treated as CN "
            f"{CN_FALLBACK}: {unknown}")
        for k in unknown:
            lut[k, :] = CN_FALLBACK
    cn_perv = lut[lc, hsg].astype(np.float32)

    # TR-55 composite CN: the impervious fraction runs off at CN 98, the rest
    # at the pervious CN for its cover and soil.
    f_imp = np.clip(imp.astype(np.float32), 0, 100) / 100.0
    cn = cn_perv + f_imp * (CN_IMPERVIOUS - cn_perv)
    cn = np.rint(cn).clip(CN_MIN, CN_MAX).astype(np.uint8)
    cn[lc == 0] = 0                               # no land cover -> no CN
    del cn_perv

    profile.update(dtype="uint8", count=1, nodata=0, compress="deflate",
                   predictor=2, tiled=True, driver="GTiff")
    with rasterio.open(out, "w", **profile) as dst:
        dst.write(cn, 1)

    rec = {"name": name, "built": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "seconds": round(time.time() - t0, 1),
           "inputs": {"landcover": os.path.basename(lc_path),
                      "impervious": os.path.basename(imp_path),
                      "mapunitpoly": os.path.basename(mu_path),
                      "hydgrp": os.path.basename(hg_path)},
           "rules": {"dual_hsg": "A/D, B/D, C/D -> D (undrained assumption)",
                     "hsg_gap": "nearest mapped cell (Euclidean, 30 m grid)",
                     "impervious": "composite CN = CN_perv + f_imp*(98 - CN_perv)",
                     "wetlands": "NLCD 90/95 -> CN 98 for every soil group",
                     "cn_fallback_outside_grid": CN_FALLBACK},
           "cells": int(lc.size),
           "landcover_pct_aoi_land": {
               int(k): round(100 * float(v) / nland, 3)
               for k, v in zip(*np.unique(lc[land], return_counts=True))},
           "hsg_pct_aoi_land_after_fill": {
               HSG_NAMES.get(int(k), str(int(k))): round(100 * float(v) / nland, 3)
               for k, v in zip(*np.unique(hsg[land], return_counts=True))},
           "impervious_mean_pct_aoi_land": round(float(imp[land].mean()), 2),
           "cn_mean_aoi_land": round(float(cn[land].mean()), 2),
           "cn_percentiles_aoi_land": {str(p): int(np.percentile(cn[land], p))
                                       for p in (5, 25, 50, 75, 95)},
           "cn_hist_aoi_land": {int(k): int(v)
                                for k, v in zip(*np.unique(cn[land],
                                                           return_counts=True))}}
    rec.update(hsg_stats)
    with open(out_json, "w") as f:
        json.dump(rec, f, indent=1)
    log(f"-> {out} ({os.path.getsize(out)/2**20:.1f} MB) | mean CN over "
        f"AOI land {rec['cn_mean_aoi_land']} | "
        f"{rec['seconds']:.0f}s")
    log(f"-> {out_json}")
    return out


# ------------------------------------------------------- stage 2: DEM grid --
def build_tiles(name, dem_dir, aoi_path, force=False, log=print):
    """One CN raster per DEM tile, on that tile's exact grid."""
    from scenario import select_tiles           # lazy: scenario imports cn
    root = data_root()
    src_path = os.path.join(root, "cn", f"cn30_{name}.tif")
    if not os.path.exists(src_path):
        sys.exit(f"missing {src_path} — run `cn.py grid` first")
    out_dir = os.path.join(root, "cn", f"tiles_{name}")
    os.makedirs(out_dir, exist_ok=True)
    tiles = select_tiles(dem_dir, aoi_path, 0.0)
    if not tiles:
        sys.exit(f"no DEM tiles meeting {aoi_path} in {dem_dir}")
    log(f"{len(tiles)} DEM tiles -> {out_dir}")

    with rasterio.open(src_path) as src:
        src_arr = src.read(1)
        src_transform, src_crs = src.transform, src.crs
    bad = 0
    for tp in tiles:
        base = os.path.basename(tp)[:-4]
        outp = os.path.join(out_dir, f"cn_{base}.tif")
        if os.path.exists(outp) and not force:
            log(f"  {base}: exists, kept")
            continue
        t0 = time.time()
        with rasterio.open(tp) as d:
            shape, transform, crs = (d.height, d.width), d.transform, d.crs
        dst = np.zeros(shape, dtype="uint8")
        reproject(src_arr, dst, src_transform=src_transform, src_crs=src_crs,
                  dst_transform=transform, dst_crs=crs,
                  src_nodata=0, dst_nodata=0, resampling=Resampling.nearest)
        # A hole only matters where the DEM has ground: those cells shed real
        # water into real pools. Holes over DEM nodata are outside the product.
        with rasterio.open(tp) as d:
            demmask = d.read_masks(1) > 0
        holes = int(((dst == 0) & demmask).sum())
        del demmask
        with rasterio.open(outp, "w", driver="GTiff", count=1, dtype="uint8",
                           crs=crs, transform=transform, height=shape[0],
                           width=shape[1], nodata=0, compress="deflate",
                           predictor=2, tiled=True) as o:
            o.write(dst, 1)
        log(f"  {base}: {shape[1]}x{shape[0]} "
            f"({os.path.getsize(outp)/2**20:.1f} MB, {time.time()-t0:.0f}s)"
            + (f" | WARNING {holes:,} DEM-valid cells with no CN — widen the "
               f"fetch margin and rebuild" if holes else ""))
        bad += holes
    if bad:
        log(f"WARNING: {bad:,} cells carry DEM ground but no curve number; "
            f"scenario.py will load them at the stated fallback CN "
            f"{CN_FALLBACK}. Re-run fetch_cn_inputs.py with a larger margin "
            f"so the CN grid covers the whole DEM mosaic, then `cn.py tiles "
            f"--force`.")
    return out_dir


if __name__ == "__main__":
    force = "--force" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--force"]
    if args[0] == "grid":
        build_grid(args[1], args[2], force=force)
    elif args[0] == "tiles":
        build_tiles(args[1], args[2], args[3], force=force)
    else:
        sys.exit(__doc__)
