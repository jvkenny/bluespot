#!/usr/bin/env python3
"""Fill-spill rainfall scenario model (docs/MODEL.md v0.4).

For a given rain depth R, estimates how full each terrain depression gets:

  1. stage-storage per pool  - from raw vs. filled DEM (sorted cell depths)
  2. catchment per pool      - D8 steepest descent on the FILLED DEM; every
                               cell routes to a terminal pool, open water, or
                               the domain edge (pointer doubling)
  3. loading                 - PER CELL: the NRCS curve number method turns
                               rain depth into runoff depth using that cell's
                               land cover, imperviousness and soil
                               (pipeline/cn.py), then the uniform
                               drainage-capacity term is taken off:
                                 S  = 1000/CN - 10                  (inches)
                                 Q  = (R-0.2S)^2/(R+0.8S), R > 0.2S (inches)
                                 net = max(0, 25.4*Q - DRAIN_MM)        (mm)
                               Runoff is summed over each pool's catchment by
                               the D8 assignment from step 2.
  4. spill cascade           - pools over capacity pass excess to the pool
                               their lowest adjacent outside cell drains to
                               (Barnes fill-spill-merge, simplified);
                               processed in topological order, cycles merged
                               conservatively (excess marked exported)

STILL TERRAIN SCREENING, NOT A FLOOD PREDICTION. No sewers/pipes (beyond the
uniform D assumption), no hydraulics, no timing. **D is now the only uniform
term in the model** — runoff generation varies cell by cell.

Two entry points, sharing one model core (`solve`):

Small AOI (single raster fits in RAM):
  scenario.py <dem.tif> <aoi.geojson> <water.geojson> <out_dir> <name>
Writes <out_dir>/<name>_depth_<sid>.tif per scenario (same conventions as
bluespot.py: float32 m, 0 = dry, nan = open water/nodata, cropped to AOI)
plus <out_dir>/<name>_scenarios.json (per-scenario stats for the viewer).

Citywide (per-DEM-tile chunks with a halo, then merged COGs):
  scenario.py --chunked <dem_dir> <aoi.geojson> <water.geojson> <chunk_dir> \
              <out_dir> [halo_m] [jobs]
Each USGS 10 km tile becomes one chunk (core + halo read from a VRT mosaic of
all tiles), run in its OWN SUBPROCESS so the allocator cannot retain arenas
across chunks. Per-chunk rasters are then mosaicked into one COG per
scenario, and stats aggregate into <out_dir>/chicago_scenarios.json.

  scenario.py --chunk <vrt> <tile.tif> <aoi> <water> <chunk_dir> <halo_m> \
              [cn_vrt]
is the single-chunk worker (invoked by --chunked; runnable standalone).

Two flags may appear anywhere in the command line and apply to every entry
point. Both are passed to chunk subprocesses through the environment, so a
chunked run cannot disagree with itself:

  --rungs 0.5,1,1.5,2,3.34,5,7.58,8.57   the rain depths to solve, inches.
        Default: the four labelled bookmarks. Depths that coincide with a
        bookmark keep the bookmark's id and label, so a ladder is a superset
        of the bookmarks rather than a parallel universe.
  --cn <name>    which curve-number tile set under <data_root>/cn/ to use.
        Default: the AOI file's stem (chicago.geojson -> chicago).

CHUNKING CAVEAT: catchments and spill cascades are solved per chunk, so both
truncate at the halo boundary. See docs/MODEL.md — the bias is toward
UNDER-collecting (and so under-storing) for pools whose contributing area
reaches beyond the halo.
"""
import glob, json, os, resource, subprocess, sys, time
from collections import deque
import numpy as np
import rasterio
from rasterio.windows import from_bounds, Window
from rasterio.warp import transform_geom
from rasterio.features import rasterize
from skimage.morphology import reconstruction
from skimage.measure import label

from bluespot import load_geoms, geom_bounds, _core_bounds, MIN_DEPTH, GDAL
from cn import CN_FALLBACK, runoff_mm_by_cn
from paths import data_root

# ---- the one remaining uniform assumption (docs/MODEL.md + viewer note) ----
DRAIN_MM = 10.0   # drainage capacity: mm of runoff removed per event by
                  # sewers/inlets. An assumption, not data - the real network
                  # is not public. Adjust and re-run to test. Everything else
                  # about runoff generation now varies per cell, from the
                  # curve-number grid (pipeline/cn.py).

# Rainfall bookmarks. ISWS values verified 2026-08-17 (see data/SOURCES.md):
# Bulletin 70 (Huff & Angel 1989) NE Illinois 100-yr 24-hr = 7.58 in;
# Bulletin 75 (ISWS, March 2020) Section 2 (Northeast) 24-hr:
#   2-yr = 3.34 in, 100-yr = 8.57 in.
BOOKMARKS = [
    # id, rain inches, short label, provenance
    ("r10",       1.00, "1.0″", "nuisance rain (reference, not a design storm)"),
    ("b75_2yr",   3.34, "3.34″", "Bulletin 75 2-yr 24-hr, NE Illinois"),
    ("b70_100yr", 7.58, "7.58″", "Bulletin 70 100-yr 24-hr (superseded 1989 standard)"),
    ("b75_100yr", 8.57, "8.57″", "Bulletin 75 100-yr 24-hr (current standard)"),
]
FULL_PROV = "full fill — static upper envelope, every pool at capacity"
RUNG_PROV = "ladder rung (interpolation stop, not a design storm)"


def scenarios(spec=None):
    """The rain depths to solve, as (id, inches, label, provenance).

    `spec` is a comma-separated list of depths in inches; empty or None means
    the four labelled bookmarks. A rung that lands on a bookmark depth keeps
    the bookmark's id, label and provenance, so ladder outputs stay
    file-compatible with the bookmark outputs the viewer already knows."""
    if spec is None:
        spec = os.environ.get("BLUESPOT_RAIN_IN", "")
    spec = (spec or "").strip()
    if not spec:
        return list(BOOKMARKS)
    depths = sorted({round(float(x), 4) for x in spec.split(",") if x.strip()})
    out = []
    for d in depths:
        bm = next((b for b in BOOKMARKS if abs(b[1] - d) < 1e-9), None)
        out.append(bm or (f"p{int(round(d * 100)):04d}", d,
                          f"{d:g}″".replace(".0″", ".0″"), RUNG_PROV))
    return out


def cn_name(aoi_path):
    """Which <data_root>/cn/ tile set backs this AOI."""
    n = os.environ.get("BLUESPOT_CN_NAME", "").strip()
    return n or os.path.basename(aoi_path).split(".")[0]

# The citywide mosaic is pinned to ONE lidar acquisition (data/SOURCES.md #1):
# the DEM folder on Drive is shared and may also hold tiles from other
# projects (IL_MidNorth_D22, IL_10CountyNRCS_D23) and from wider-area AOIs.
# Chunk cores = tiles of this project whose 10 km core meets the AOI + halo.
DEM_PROJECT = "IL_4_County_QL1_LiDAR_2016"

SQ2 = 2.0 ** 0.5
OFF = [(-1, -1, SQ2), (-1, 0, 1.0), (-1, 1, SQ2), (0, -1, 1.0),
       (0, 1, 1.0), (1, -1, SQ2), (1, 0, 1.0), (1, 1, SQ2)]


def shift(a, dr, dc, fill):
    """shifted[r, c] = a[r+dr, c+dc]; out-of-bounds = fill."""
    H, W = a.shape
    out = np.full(a.shape, fill, dtype=a.dtype)
    out[max(0, -dr):H + min(0, -dr), max(0, -dc):W + min(0, -dc)] = \
        a[max(0, dr):H + min(0, dr), max(0, dc):W + min(0, dc)]
    return out


def read_domain(src, win, water_geoms):
    """DEM + validity + water mask for a window of an open raster."""
    dem = src.read(1, window=win).astype("float32")
    transform = src.window_transform(win)
    valid = np.isfinite(dem)
    if src.nodata is not None:
        valid &= dem != src.nodata
    water = rasterize(water_geoms, out_shape=dem.shape, transform=transform,
                      fill=0, default_value=1, dtype="uint8").astype(bool)
    return dem, valid, water, transform


def fill_depressions(dem, valid, water):
    """Morphological reconstruction by erosion; outlets = array edges + water.
    Identical to bluespot.compute_depth's fill, but returns the filled surface
    (float32, invalid cells raised to `hi`)."""
    hi = np.float32(dem[valid].max() + 100.0)
    dem_w = np.where(valid, dem, hi).astype("float32")
    seed = np.full_like(dem_w, hi)
    for sl in (np.s_[0, :], np.s_[-1, :], np.s_[:, 0], np.s_[:, -1]):
        seed[sl] = dem_w[sl]
    seed[water] = dem_w[water]          # open water drains
    filled = reconstruction(seed, dem_w, method="erosion").astype("float32")
    del seed
    return dem_w, filled


def flow_routing(F, terminal, log=print):
    """D8 steepest descent on the filled surface F (inf where invalid).
    `terminal` marks cells that absorb flow (pools, water, invalid, border).
    Flats drain via equal-elevation neighbours that already drain (guaranteed
    to exist on a filled surface outside pools). Returns the flat index of the
    terminal each cell routes to."""
    H, W = F.shape
    idx = np.arange(H * W, dtype=np.int32).reshape(H, W)
    ds = idx.copy()
    best = np.zeros((H, W), dtype="float32")
    with np.errstate(invalid="ignore"):
        for dr, dc, dist in OFF:
            drop = (F - shift(F, dr, dc, np.float32(np.inf))) / np.float32(dist)
            better = (~terminal) & (drop > best)
            if better.any():
                ds[better] = shift(idx, dr, dc, np.int32(-1))[better]
                best[better] = drop[better]
            del drop, better

    # flat resolution: adopt an equal-elevation neighbour that already drains
    resolved = terminal | (best > 0)
    del best
    pending = ~resolved
    for it in range(2000):
        if not pending.any():
            break
        progress = False
        for dr, dc, _ in OFF:
            take = pending & shift(resolved, dr, dc, False) & \
                   (shift(F, dr, dc, np.float32(np.inf)) == F)
            if take.any():
                ds[take] = shift(idx, dr, dc, np.int32(-1))[take]
                resolved |= take
                pending &= ~take
                progress = True
            del take
        if not progress:
            break
    n_stuck = int(pending.sum())
    if n_stuck:
        log(f"  warning: {n_stuck:,} flat cells unresolved (treated as exported)")
    del idx, resolved, pending

    # pointer doubling to the terminal each cell drains to
    r = ds.reshape(-1)
    for _ in range(64):
        nxt = r[r]
        if np.array_equal(nxt, r):
            break
        r = nxt
    return r


def spill_edges(lab, F, root_pool_flat, npools):
    """For each pool, the lowest valid adjacent outside cell that does NOT
    drain straight back into the pool; downstream = the pool (or export=0)
    that cell drains to. Returns (target[npools+1], spill_elev[npools+1])."""
    H, W = lab.shape
    idx = np.arange(H * W, dtype=np.int32).reshape(H, W)
    ps, cs, fs = [], [], []
    for dr, dc, _ in OFF:
        nb_lab = shift(lab, dr, dc, np.int32(0))
        m = (nb_lab > 0) & (nb_lab != lab) & np.isfinite(F)
        if m.any():
            ps.append(nb_lab[m]); cs.append(idx[m]); fs.append(F[m])
        del nb_lab, m
    del idx
    ps = np.concatenate(ps); cs = np.concatenate(cs); fs = np.concatenate(fs)
    rp = root_pool_flat[cs]
    keep = rp != ps                      # exclude candidates draining back in
    ps, fs, rp = ps[keep], fs[keep], rp[keep]
    del cs, keep
    order = np.lexsort((fs, ps))
    ps, fs, rp = ps[order], fs[order], rp[order]
    del order
    first = np.searchsorted(ps, np.arange(1, npools + 1))
    target = np.zeros(npools + 1, dtype=np.int64)
    elev = np.full(npools + 1, np.nan)
    ok = first < len(ps)
    ok &= np.where(ok, ps[np.minimum(first, len(ps) - 1)] == np.arange(1, npools + 1), False)
    pi = np.arange(1, npools + 1)[ok]
    target[pi] = rp[first[ok]]
    elev[pi] = fs[first[ok]]
    return target, elev


def cascade(load, cap, target, pour):
    """Fill-spill in topological order; cycles filled by pour elevation with
    residual excess marked exported. Returns (stored, exported_m3)."""
    n = len(cap) - 1
    inflow = load.copy()
    stored = np.zeros(n + 1)
    indeg = np.bincount(target[1:][target[1:] > 0], minlength=n + 1)
    processed = np.zeros(n + 1, dtype=bool)
    exported = 0.0
    q = deque(np.flatnonzero((indeg[1:] == 0)) + 1)
    while q:
        p = int(q.popleft())
        processed[p] = True
        stored[p] = min(inflow[p], cap[p])
        over = inflow[p] - stored[p]
        t = int(target[p])
        if over > 0:
            if t > 0:
                inflow[t] += over
            else:
                exported += over
        if t > 0:
            indeg[t] -= 1
            if indeg[t] == 0 and not processed[t]:
                q.append(t)
    # anything left sits on a cycle (mutual spills at equal saddles)
    left = np.flatnonzero(~processed[1:]) + 1
    seen = set()
    for p0 in left:
        if p0 in seen or processed[p0]:
            continue
        cyc, p = [], int(p0)
        while p > 0 and not processed[p] and p not in seen:
            seen.add(p); cyc.append(p); p = int(target[p])
        total = sum(inflow[m] for m in cyc)
        for m in sorted(cyc, key=lambda m: pour[m]):
            stored[m] = min(cap[m], total)
            total -= stored[m]
            processed[m] = True
        exported += total
    return stored, exported


class PoolIndex:
    """Pool cells sorted by (pool, elevation) — the stage-storage index.
    Built once per domain and reused for every rainfall scenario."""

    def __init__(self, lab_flat, z_flat, dfull_flat, npools):
        cells = np.flatnonzero(lab_flat)
        pl = lab_flat[cells]
        z = z_flat[cells]
        order = np.lexsort((z, pl))
        self.cells = cells[order]
        self.z = z[order]
        self.pl = pl[order]
        self.dfull = dfull_flat[self.cells]
        self.starts = np.searchsorted(self.pl, np.arange(1, npools + 2))
        del order, cells, pl, z

    def levels(self, stored, cap, pour, cell_area, shape):
        """Per-cell scenario depth from per-pool stored volume, exact
        stage-storage (cells submerge bottom-up)."""
        depth = np.zeros(shape[0] * shape[1], dtype="float32")
        wet = stored > 0
        full = wet & (stored >= cap * (1.0 - 1e-9))
        # pools filled to the brim: the scenario depth IS the static depth
        fullcell = full[self.pl]
        depth[self.cells[fullcell]] = self.dfull[fullcell]
        del fullcell
        # partially filled pools: solve the water surface analytically
        for p in np.flatnonzero(wet & ~full):
            s, e = self.starts[p - 1], self.starts[p]
            zs = self.z[s:e].astype(np.float64)
            V = stored[p] / cell_area
            S = np.cumsum(zs)
            j = np.arange(1, len(zs))
            need = j * zs[1:] - S[:-1]      # volume to raise surface to zs[j]
            m = int(np.searchsorted(need, V, side="right"))
            w = (V + S[m]) / (m + 1)
            depth[self.cells[s:e]] = np.maximum(w - zs, 0.0)
        return depth.reshape(shape)


def pool_cn_hist(root_pool, cn_flat, valid_flat, npools, log=print):
    """Cells per (pool, curve number), the whole basis of the loading step.

    Built once per domain, in row slabs so no full-size int64 key array is
    ever materialised, and reduced to only the CN values the domain actually
    contains (typically ~70 of the 101 possible). Once this exists the D8
    result can be freed: every rainfall rung is then a matrix-vector product
    against a 101-entry runoff lookup, which is what makes a 12-rung ladder
    cost about the same as one rung.

    Returns (hist[npools+1, ncn] int64, cn_values[ncn])."""
    counts = np.bincount(cn_flat, minlength=256)
    present = np.flatnonzero(counts).astype(np.int32)
    ncn = len(present)
    remap = np.zeros(256, dtype=np.int64)
    remap[present] = np.arange(ncn, dtype=np.int64)
    M = (npools + 1) * ncn
    hist = np.zeros(M, dtype=np.int64)
    slab = 1 << 24
    for s in range(0, root_pool.size, slab):
        sl = slice(s, min(s + slab, root_pool.size))
        v = valid_flat[sl]
        if not v.any():
            continue
        k = root_pool[sl][v].astype(np.int64) * ncn + remap[cn_flat[sl][v]]
        hist += np.bincount(k, minlength=M)
        del k, v
    log(f"  pool x CN histogram: {npools+1:,} x {ncn} "
        f"(CN {present.min()}-{present.max()})")
    return hist.reshape(npools + 1, ncn), present


def solve(dem, valid, water, cell_area, cn, rungs=None, log=print):
    """The model core. Yields (sid, depth2d, stats) for each rainfall rung
    and finally for the static full fill.

    `cn` is a uint8 curve-number array on the same grid as `dem` (0 = no
    curve number, loaded at the stated CN_FALLBACK).

    Arrays are consumed/freed as the solve proceeds so peak RSS stays near
    ~7 GB for a 12k x 12k domain."""
    rungs = scenarios() if rungs is None else rungs
    t0 = time.time()
    dem_w, filled = fill_depressions(dem, valid, water)
    log(f"  fill {time.time()-t0:.0f}s")

    depth_full = filled - dem_w
    pool_mask = valid & ~water & (depth_full >= MIN_DEPTH)
    lab = label(pool_mask, connectivity=2).astype(np.int32)
    del pool_mask
    npools = int(lab.max())
    lab_flat = lab.reshape(-1)
    sel = lab_flat > 0
    cap = np.bincount(lab_flat[sel], weights=depth_full.reshape(-1)[sel],
                      minlength=npools + 1) * cell_area
    pour = np.zeros(npools + 1)
    pour[lab_flat[sel]] = filled.reshape(-1)[sel]
    del sel
    log(f"  {npools:,} pools, capacity {cap.sum():,.0f} m3")

    F = np.where(valid, filled, np.float32(np.inf)).astype("float32")
    del filled
    terminal = (~valid) | water | (lab > 0)
    terminal[0, :] = terminal[-1, :] = terminal[:, 0] = terminal[:, -1] = True
    t1 = time.time()
    root = flow_routing(F, terminal, log=log)
    del terminal
    root_pool = lab_flat[root]                       # 0 = water/edge/export
    del root
    log(f"  routing {time.time()-t1:.0f}s")

    t2 = time.time()
    target, _ = spill_edges(lab, F, root_pool, npools)
    del F, lab
    log(f"  spill edges {time.time()-t2:.0f}s")

    t5 = time.time()
    hist, cn_vals = pool_cn_hist(root_pool, cn.reshape(-1), valid.reshape(-1),
                                 npools, log=log)
    del root_pool
    catch_area = hist.sum(axis=1) * cell_area
    n_no_cn = int(hist[:, 0].sum()) if cn_vals[0] == 0 else 0
    log(f"  catchment {catch_area[1:].sum():,.0f} m2 to pools, "
        f"{catch_area[0]:,.0f} m2 to water/edge | "
        f"{time.time()-t5:.0f}s"
        + (f" | WARNING {n_no_cn:,} contributing cells have no curve number, "
           f"loaded at CN {CN_FALLBACK}" if n_no_cn else ""))

    t3 = time.time()
    pi = PoolIndex(lab_flat, dem_w.reshape(-1), depth_full.reshape(-1), npools)
    del lab_flat
    log(f"  stage-storage index {time.time()-t3:.0f}s")

    shape = dem_w.shape
    del dem_w
    nan_mask = (~valid) | water

    contrib_area = float(catch_area[1:].sum())
    for sid, inches, short, prov in rungs:
        t4 = time.time()
        rain_mm = inches * 25.4
        # runoff per curve number, then the uniform drainage capacity off the
        # top of each cell's runoff (not off the pool's total): sewers and
        # inlets take their share wherever the water is made.
        net_m = np.maximum(0.0, runoff_mm_by_cn(rain_mm / 25.4)[cn_vals]
                           - DRAIN_MM) / 1000.0
        load = (hist @ net_m) * cell_area
        load[0] = 0.0
        stored, exported = cascade(load, cap, target, pour)
        d = pi.levels(stored, cap, pour, cell_area, shape)
        d[d < MIN_DEPTH] = 0.0
        d[nan_mask] = np.nan
        loaded = float(load[1:].sum())
        stored_t = float(stored[1:].sum())
        imbal = (loaded - stored_t - exported) / loaded if loaded > 0 else 0.0
        # area-weighted mean net runoff over the contributing area: the single
        # number that replaces v0.3's "net_mm", for like-for-like comparison
        net_mean = (loaded / contrib_area * 1000.0) if contrib_area else 0.0
        rec = {"id": sid, "rain_in": inches, "rain_mm": round(rain_mm, 1),
               "label": short, "provenance": prov,
               "net_mm_mean": round(net_mean, 3),
               "contrib_area_m2": contrib_area,
               "loaded_m3": loaded,
               "stored_m3": stored_t, "exported_m3": exported,
               "balance_rel_err": imbal,
               "pools_at_capacity": int(np.sum(stored[1:] >= cap[1:] * (1 - 1e-9))),
               "n_pools": npools}
        log(f"  {sid:>10}: net {net_mean:5.1f} mm mean | stored {stored_t:>14,.0f} "
            f"| exported {exported:>14,.0f} | imbalance {imbal:+.2e} "
            f"| {time.time()-t4:.0f}s")
        yield sid, d, rec
        del d, stored, load

    dfull = depth_full
    dfull[dfull < MIN_DEPTH] = 0.0
    dfull[nan_mask] = np.nan
    yield "full", dfull, {"id": "full", "rain_in": None, "rain_mm": None,
                          "label": "max", "provenance": FULL_PROV,
                          "loaded_m3": None, "stored_m3": float(cap.sum()),
                          "exported_m3": None, "balance_rel_err": 0.0,
                          "pools_at_capacity": npools, "n_pools": npools}


def _crop_stats(d, r0, c0, rh, cw, cell_area):
    """Crop the halo off, then summarise the in-product core."""
    dc = d[r0:r0 + rh, c0:c0 + cw]
    fin = np.isfinite(dc)
    wet = fin & (dc > 0)
    return dc, {"core_cells": int(fin.sum()), "core_wet_cells": int(wet.sum()),
                "core_stored_m3": float(np.nansum(dc)) * cell_area,
                "core_max_depth_m": float(np.nanmax(dc)) if wet.any() else 0.0}


# -------------------------------------------------------- curve numbers ----
def cn_read_window(cn_vrt, transform, shape, log=print):
    """Read the curve-number mosaic over exactly the window a DEM chunk used.

    The CN tiles were written on the DEM tiles' own grids (pipeline/cn.py
    stage 2), so this is an index-for-index read with no resampling — and the
    assertion below is what proves it stayed that way."""
    with rasterio.open(cn_vrt) as src:
        win = from_bounds(*rasterio.transform.array_bounds(
            shape[0], shape[1], transform), src.transform
                          ).round_offsets().round_lengths()
        cn = src.read(1, window=win, boundless=True, fill_value=0)
        wt = src.window_transform(win)
    if cn.shape != shape:
        cn = np.zeros(shape, dtype="uint8") if cn.size == 0 else \
            cn[:shape[0], :shape[1]]
    if abs(wt.c - transform.c) > 0.5 or abs(wt.f - transform.f) > 0.5 \
            or abs(wt.a - transform.a) > 1e-6:
        raise SystemExit(f"curve-number mosaic is not on the DEM grid: "
                         f"{wt} vs {transform}")
    return cn.astype("uint8")


def cn_warp_domain(name, transform, shape, crs, log=print):
    """Curve numbers for a domain that has no DEM-tile counterpart (the pilot
    single-raster path): nearest-resample the 30 m grid into it."""
    from rasterio.warp import Resampling, reproject
    src_path = os.path.join(data_root(), "cn", f"cn30_{name}.tif")
    if not os.path.exists(src_path):
        sys.exit(f"missing {src_path} — run `cn.py grid <aoi> {name}` first")
    with rasterio.open(src_path) as src:
        out = np.zeros(shape, dtype="uint8")
        reproject(src.read(1), out, src_transform=src.transform,
                  src_crs=src.crs, dst_transform=transform, dst_crs=crs,
                  src_nodata=0, dst_nodata=0, resampling=Resampling.nearest)
    log(f"  curve numbers from {os.path.basename(src_path)}")
    return out


def _cn_record(name):
    """The curve-number build record, folded into the output JSON so the
    published numbers carry their own provenance."""
    p = os.path.join(data_root(), "cn", f"cn30_{name}.json")
    if not os.path.exists(p):
        return {"name": name, "note": "build record not found"}
    d = json.load(open(p))
    return {k: d[k] for k in ("name", "built", "inputs", "rules",
                              "cn_mean_aoi_land", "cn_percentiles_aoi_land",
                              "impervious_mean_pct_aoi_land",
                              "hsg_pct_aoi_land_after_fill",
                              "hsg_gap_fraction_aoi_land",
                              "hsg_dual_fraction_aoi_land") if k in d}


# ---------------------------------------------------------------- pilot ----
def main(dem_path, aoi_path, water_path, out_dir, name, buffer_m=1000.0):
    """Single-domain entry point for small AOIs."""
    buffer_m = float(buffer_m)
    os.makedirs(out_dir, exist_ok=True)
    with rasterio.open(dem_path) as src:
        x0, y0, x1, y1 = geom_bounds(load_geoms(aoi_path, src.crs))
        win = from_bounds(x0 - buffer_m, y0 - buffer_m, x1 + buffer_m,
                          y1 + buffer_m, src.transform).round_offsets().round_lengths()
        win = win.intersection(Window(0, 0, src.width, src.height))
        wgeoms = load_geoms(water_path, src.crs)
        dem, valid, water, transform = read_domain(src, win, wgeoms)
        profile = src.profile
    cell_area = abs(transform.a * transform.e)

    cwin = from_bounds(x0, y0, x1, y1, transform).round_offsets().round_lengths()
    r0, c0 = int(cwin.row_off), int(cwin.col_off)
    rh, cw = int(cwin.height), int(cwin.width)
    out_transform = rasterio.transform.Affine(
        transform.a, transform.b, transform.c + c0 * transform.a,
        transform.d, transform.e, transform.f + r0 * transform.e)
    profile.update(height=rh, width=cw, transform=out_transform, dtype="float32",
                   nodata=np.nan, compress="deflate", predictor=2, count=1,
                   driver="GTiff")

    cname = cn_name(aoi_path)
    cn = cn_warp_domain(cname, transform, dem.shape, profile["crs"])
    rungs = scenarios()
    meta = {"assumptions": _assumptions(cname),
            "rungs_in": [r[1] for r in rungs], "scenarios": []}
    for sid, d, rec in solve(dem, valid, water, cell_area, cn, rungs):
        dc, cs = _crop_stats(d, r0, c0, rh, cw, cell_area)
        if sid != "full":
            with rasterio.open(os.path.join(out_dir, f"{name}_depth_{sid}.tif"),
                               "w", **profile) as dst:
                dst.write(dc, 1)
        rec.update(cs)
        rec["wet_pct"] = round(100.0 * cs["core_wet_cells"] / cs["core_cells"], 2)
        meta["scenarios"].append(rec)
        print(f"  {sid:>10}: wet {rec['wet_pct']:5.2f}%")
    out_json = os.path.join(out_dir, f"{name}_scenarios.json")
    json.dump(meta, open(out_json, "w"), indent=1)
    print(f"-> {out_json}")


def _assumptions(cname=None):
    return {
        "runoff": "NRCS curve number, per cell (TR-55). "
                  "S = 1000/CN - 10 in; Q = (P-0.2S)^2/(P+0.8S) for P > 0.2S. "
                  "CN from NLCD 2021 land cover + percent imperviousness and "
                  "SSURGO hydrologic soil group (pipeline/cn.py, "
                  "data/SOURCES.md #9-#12)",
        "drain_mm": DRAIN_MM,
        "drain_note": "mm of runoff removed per event by sewers and inlets, "
                      "taken off each cell's runoff. The ONLY uniform term "
                      "left in the model — the real network is not public "
                      "data. Adjust DRAIN_MM in pipeline/scenario.py and "
                      "re-run to test.",
        "cn_fallback": CN_FALLBACK,
        "curve_numbers": _cn_record(cname) if cname else None,
        "note": "terrain screening, not a flood prediction; the drainage "
                "capacity D is a stated assumption (pipeline/scenario.py)"}


# ------------------------------------------------------------- citywide ----
def select_tiles(dem_dir, aoi_path, margin_m=0.0):
    """DEM_PROJECT tiles whose 10 km core meets the AOI bounding box grown by
    `margin_m`.

    Deliberately NOT a bare glob of dem_dir — that folder is a shared Drive
    store which also holds other lidar projects and tiles fetched for
    wider-area AOIs. Selecting by project + AOI keeps the citywide mosaic
    reproducible no matter what else lands there.

    `margin_m=0` gives the chunk cores, which are also the VRT mosaic
    sources: halo context comes from neighbouring core tiles, and the
    outermost halo ring falls outside the mosaic and reads nodata. That is
    exactly how bluespot.py builds the static citywide layer, so the two stay
    cell-for-cell consistent — and it makes the mosaic a function of the AOI
    alone, rather than of whatever else happens to be sitting in the shared
    Drive folder when the run starts."""
    cand = sorted(os.path.abspath(t)
                  for t in glob.glob(os.path.join(dem_dir, f"*{DEM_PROJECT}*.tif")))
    if not cand:
        return []
    with rasterio.open(cand[0]) as s:
        crs = s.crs
    ax0, ay0, ax1, ay1 = geom_bounds(load_geoms(aoi_path, crs))
    ax0, ay0 = ax0 - margin_m, ay0 - margin_m
    ax1, ay1 = ax1 + margin_m, ay1 + margin_m
    keep = []
    for t in cand:
        cx0, cy0, cx1, cy1 = _core_bounds(t)
        if cx0 < ax1 and cx1 > ax0 and cy0 < ay1 and cy1 > ay0:
            keep.append(t)
    return keep


def chunk(vrt, tile, aoi_path, water_path, chunk_dir, halo_m=1000.0,
          cn_vrt=None):
    """One DEM tile: core + halo domain, solved and written per scenario."""
    halo_m = float(halo_m)
    cn_vrt = cn_vrt or os.path.join(os.path.dirname(vrt), "cn_mosaic.vrt")
    name = os.path.basename(tile).replace(".tif", "")
    t0 = time.time()
    log = lambda *a: print(*a, flush=True)
    cx0, cy0, cx1, cy1 = _core_bounds(tile)
    with rasterio.open(vrt) as src:
        win = from_bounds(cx0 - halo_m, cy0 - halo_m, cx1 + halo_m,
                          cy1 + halo_m, src.transform
                          ).round_offsets().round_lengths()
        try:
            win = win.intersection(Window(0, 0, src.width, src.height))
        except rasterio.errors.WindowError:
            log(f"{name}: outside the DEM mosaic, skipped")
            json.dump({"tile": name, "skipped": "outside mosaic"},
                      open(os.path.join(chunk_dir, f"chunk_{name}.json"), "w"))
            return
        crs = src.crs
        transform = src.window_transform(win)
        shape = (int(win.height), int(win.width))
        ageoms = load_geoms(aoi_path, crs)
        aoi_mask = rasterize(ageoms, out_shape=shape, transform=transform,
                             fill=0, default_value=1, dtype="uint8").astype(bool)
        if not aoi_mask.any():
            log(f"{name}: outside AOI, skipped")
            json.dump({"tile": name, "skipped": "outside AOI"},
                      open(os.path.join(chunk_dir, f"chunk_{name}.json"), "w"))
            return
        wgeoms = load_geoms(water_path, crs)
        dem, valid, water, transform = read_domain(src, win, wgeoms)
    if not valid.any():
        log(f"{name}: all nodata, skipped")
        json.dump({"tile": name, "skipped": "all nodata"},
                  open(os.path.join(chunk_dir, f"chunk_{name}.json"), "w"))
        return
    cell_area = abs(transform.a * transform.e)
    log(f"{name}: domain {shape[0]}x{shape[1]} ({shape[0]*shape[1]/1e6:.0f} Mcell), "
        f"halo {halo_m:.0f} m")

    # crop window: halo off, back to the tile core
    cwin = from_bounds(cx0, cy0, cx1, cy1, transform).round_offsets().round_lengths()
    cwin = cwin.intersection(Window(0, 0, shape[1], shape[0]))
    r0, c0 = int(cwin.row_off), int(cwin.col_off)
    rh, cw = int(cwin.height), int(cwin.width)
    out_transform = rasterio.transform.Affine(
        transform.a, transform.b, transform.c + c0 * transform.a,
        transform.d, transform.e, transform.f + r0 * transform.e)

    cn = cn_read_window(cn_vrt, transform, shape, log=log)
    rungs = scenarios()
    stats = {"tile": name, "halo_m": halo_m, "domain_cells": int(shape[0] * shape[1]),
             "rungs_in": [r[1] for r in rungs],
             "cn_mean_valid": round(float(cn[valid & (cn > 0)].mean()), 2)
                              if (valid & (cn > 0)).any() else 0.0,
             "scenarios": []}
    for sid, d, rec in solve(dem, valid, water, cell_area, cn, rungs, log=log):
        d[~aoi_mask] = np.nan            # product is masked to the city
        dc, cs = _crop_stats(d, r0, c0, rh, cw, cell_area)
        rec.update(cs)
        stats["scenarios"].append(rec)
        if not np.isfinite(dc).any():
            log(f"  {sid}: no valid land in AOI core, not written")
            continue
        outp = os.path.join(chunk_dir, f"{sid}_{name}.tif")
        with rasterio.open(outp, "w", driver="GTiff", count=1, dtype="float32",
                           crs=crs, transform=out_transform, height=rh, width=cw,
                           nodata=np.nan, compress="deflate", predictor=2,
                           tiled=True) as dst:
            dst.write(dc, 1)
        del dc
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2 ** 30
    stats["peak_rss_gb"] = round(rss, 2)
    stats["seconds"] = round(time.time() - t0, 1)
    json.dump(stats, open(os.path.join(chunk_dir, f"chunk_{name}.json"), "w"), indent=1)
    log(f"{name}: done in {stats['seconds']:.0f}s, peak RSS {rss:.1f} GB")


def chunked(dem_dir, aoi_path, water_path, chunk_dir, out_dir, halo_m=1000.0,
            jobs=1):
    halo_m, jobs = float(halo_m), int(jobs)
    tiles = select_tiles(dem_dir, aoi_path, 0.0)   # chunk cores AND VRT sources
    if not tiles:
        sys.exit(f"no {DEM_PROJECT} tiles meeting the AOI in {dem_dir}")
    os.makedirs(chunk_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    vrt = os.path.join(chunk_dir, "dem_mosaic.vrt")
    if not os.path.exists(vrt):
        subprocess.run([f"{GDAL}/gdalbuildvrt", "-q", vrt] + tiles, check=True)

    # the curve-number mosaic, built from the SAME tile list so it lands on
    # the same grid with the same footprint as the DEM mosaic
    cname = cn_name(aoi_path)
    cn_dir = os.path.join(data_root(), "cn", f"tiles_{cname}")
    cn_tiles = [os.path.join(cn_dir, f"cn_{os.path.basename(t)[:-4]}.tif")
                for t in tiles]
    missing = [t for t in cn_tiles if not os.path.exists(t)]
    if missing:
        sys.exit(f"{len(missing)} curve-number tile(s) missing from {cn_dir}, "
                 f"first: {missing[0]}\nrun: cn.py grid <aoi> {cname} && "
                 f"cn.py tiles {cname} <dem_dir> <aoi>")
    cn_vrt = os.path.join(chunk_dir, "cn_mosaic.vrt")
    if not os.path.exists(cn_vrt):
        subprocess.run([f"{GDAL}/gdalbuildvrt", "-q", cn_vrt] + cn_tiles,
                       check=True)
    rungs = scenarios()
    print(f"{len(tiles)} DEM tiles | halo {halo_m:.0f} m | {jobs} job(s) | "
          f"curve numbers '{cname}' | {len(rungs)} rung(s): "
          + ", ".join(f"{r[1]:g}\u2033" for r in rungs), flush=True)

    t_all = time.time()
    todo = [t for t in tiles
            if not os.path.exists(os.path.join(
                chunk_dir, f"chunk_{os.path.basename(t)[:-4]}.json"))]
    print(f"{len(tiles) - len(todo)} chunks already done, {len(todo)} to run",
          flush=True)
    running = []
    while todo or running:
        while todo and len(running) < jobs:
            t = todo.pop(0)
            cmd = [sys.executable, os.path.abspath(__file__), "--chunk", vrt, t,
                   aoi_path, water_path, chunk_dir, str(halo_m), cn_vrt]
            logf = open(os.path.join(chunk_dir,
                                     f"log_{os.path.basename(t)[:-4]}.txt"), "w")
            running.append((subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT,
                                             cwd=os.path.dirname(os.path.abspath(__file__))),
                            os.path.basename(t)[:-4], logf, time.time()))
            print(f"  -> started {running[-1][1]}", flush=True)
        time.sleep(5)
        for r in list(running):
            if r[0].poll() is not None:
                running.remove(r); r[2].close()
                status = "ok" if r[0].returncode == 0 else f"FAILED rc={r[0].returncode}"
                print(f"  <- {r[1]} {status} ({time.time()-r[3]:.0f}s)", flush=True)
                if r[0].returncode != 0:
                    sys.exit(f"chunk {r[1]} failed; see {chunk_dir}/log_{r[1]}.txt")
    print(f"all chunks: {time.time()-t_all:.0f}s", flush=True)
    aggregate(chunk_dir, out_dir, halo_m)


def aggregate(chunk_dir, out_dir, halo_m=1000.0, cname=None):
    """Mosaic per-chunk rasters into one COG per scenario and roll the
    per-chunk stats up into the citywide scenarios JSON."""
    halo_m = float(halo_m)
    os.makedirs(out_dir, exist_ok=True)
    cstats = [json.load(open(p)) for p in
              sorted(glob.glob(os.path.join(chunk_dir, "chunk_*.json")))]
    # a chunk with an empty core contributed halo context only — it has no
    # cells in the product and must not enter the citywide totals
    used = [c for c in cstats if "scenarios" in c
            and any(r["core_cells"] for r in c["scenarios"])]
    print(f"aggregating {len(used)} chunks ({len(cstats)-len(used)} skipped)")

    meta = {"assumptions": _assumptions(cname),
            "coverage": "City of Chicago",
            "chunking": {"tiles": len(used), "halo_m": halo_m,
                         "note": "catchments and spill cascades are solved per "
                                 "DEM-tile chunk and truncate at the halo; see "
                                 "docs/MODEL.md"},
            "scenarios": []}
    # ids come from the chunks themselves, ordered by rain depth, so a ladder
    # run and a bookmark run aggregate correctly without the aggregator having
    # to be told which rungs were solved
    seen = {}
    for c in used:
        for r in c["scenarios"]:
            seen.setdefault(r["id"], r["rain_in"])
    ids = [k for k, _ in sorted((kv for kv in seen.items() if kv[0] != "full"),
                                key=lambda kv: kv[1])]
    meta["rungs_in"] = [seen[k] for k in ids]
    ids = ids + (["full"] if "full" in seen else [])
    for sid in ids:
        recs = [r for c in used for r in c["scenarios"] if r["id"] == sid]
        cells = sum(r["core_cells"] for r in recs)
        wet = sum(r["core_wet_cells"] for r in recs)
        stored = sum(r["core_stored_m3"] for r in recs)
        d_loaded = sum(r["loaded_m3"] for r in recs) if sid != "full" else None
        # area-weighted mean net runoff over the contributing area. Older
        # chunk records predate contrib_area_m2; recover it by inverting the
        # per-chunk mean, which is exactly the quantity it was divided by.
        d_area = sum(r.get("contrib_area_m2") or
                     (r["loaded_m3"] / (r["net_mm_mean"] / 1000.0)
                      if r.get("net_mm_mean") else 0.0)
                     for r in recs) if sid != "full" else 0.0
        d_stored = sum(r["stored_m3"] for r in recs)
        d_exported = sum(r["exported_m3"] for r in recs) if sid != "full" else None
        proto = recs[0]
        rec = {"id": sid, "rain_in": proto["rain_in"], "rain_mm": proto["rain_mm"],
               "label": proto["label"], "provenance": proto["provenance"],
               "wet_pct": round(100.0 * wet / cells, 2),
               "stored_m3": round(stored),
               "land_cells": cells, "wet_cells": wet,
               "max_depth_m": round(max(r["core_max_depth_m"] for r in recs), 2)}
        # per-pool counts are deliberately NOT rolled up: chunk domains overlap
        # in the halo, so summing them would double-count. They stay per-chunk.
        if sid != "full":
            rec["net_mm_mean"] = round(1000.0 * d_loaded / d_area, 3) if d_area else 0.0
            rec["contrib_area_m2"] = round(d_area)
            rec["exported_m3"] = round(d_exported)
            rec["domain_loaded_m3"] = round(d_loaded)
            rec["domain_stored_m3"] = round(d_stored)
            rec["balance_rel_err"] = (d_loaded - d_stored - d_exported) / d_loaded
        meta["scenarios"].append(rec)
        print(f"  {sid:>10}: wet {rec['wet_pct']:5.2f}% | stored "
              f"{rec['stored_m3']:>15,} m3 | max {rec['max_depth_m']:.2f} m"
              + ("" if sid == "full" else
                 f" | balance {rec['balance_rel_err']:+.2e}"))

        if sid == "full":
            continue        # the static layer already ships as chicago_depth_cog
        chunks = sorted(glob.glob(os.path.join(chunk_dir, f"{sid}_*.tif")))
        if not chunks:
            print(f"  {sid}: no chunk rasters, COG skipped"); continue
        mvrt = os.path.join(chunk_dir, f"{sid}_mosaic.vrt")
        cog = os.path.join(out_dir, f"chicago_depth_{sid}.tif")
        if os.path.exists(cog):
            print(f"    COG exists, kept ({os.path.getsize(cog)/2**20:.0f} MB)")
            continue
        subprocess.run([f"{GDAL}/gdalbuildvrt", "-q", mvrt] + chunks, check=True)
        subprocess.run([f"{GDAL}/gdal_translate", "-q", "-of", "COG",
                        "-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=3",
                        "-co", "NUM_THREADS=ALL_CPUS", "-co", "BIGTIFF=IF_SAFER",
                        mvrt, cog], check=True)
        print(f"    COG -> {cog} ({os.path.getsize(cog)/2**20:.0f} MB)", flush=True)

    per_chunk = [{k: c[k] for k in ("tile", "seconds", "peak_rss_gb",
                                    "domain_cells", "cn_mean_valid")
                  if k in c} for c in used]
    meta["chunks"] = sorted(per_chunk, key=lambda c: c["tile"])
    meta["balance_check"] = {
        "rule": "loaded = stored + exported over each chunk's whole domain "
                "(halo included), per rung",
        "max_abs_rel_err": max((abs(r["balance_rel_err"])
                                for r in meta["scenarios"]
                                if "balance_rel_err" in r), default=0.0),
        "threshold": 1e-3}
    out_json = os.path.join(out_dir, "chicago_scenarios.json")
    json.dump(meta, open(out_json, "w"), indent=1)
    print(f"-> {out_json}")


def _pull_flag(argv, flag, env):
    """Take `--flag value` out of argv and park it in the environment, so
    chunk subprocesses inherit exactly what the parent was told."""
    if flag in argv:
        i = argv.index(flag)
        os.environ[env] = argv[i + 1]
        del argv[i:i + 2]
    return argv


if __name__ == "__main__":
    argv = list(sys.argv)
    argv = _pull_flag(argv, "--rungs", "BLUESPOT_RAIN_IN")
    argv = _pull_flag(argv, "--cn", "BLUESPOT_CN_NAME")
    if argv[1] == "--chunked":
        chunked(*argv[2:9])
    elif argv[1] == "--chunk":
        chunk(*argv[2:9])
    elif argv[1] == "--aggregate":
        aggregate(*argv[2:6])
    else:
        main(*argv[1:7])
