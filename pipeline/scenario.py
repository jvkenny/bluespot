#!/usr/bin/env python3
"""Fill-spill rainfall scenario model (docs/MODEL.md v0.2).

For a given rain depth R, estimates how full each terrain depression gets:

  1. stage-storage per pool  - from raw vs. filled DEM (sorted cell depths)
  2. catchment per pool      - D8 steepest descent on the FILLED DEM; every
                               cell routes to a terminal pool, open water, or
                               the domain edge (pointer doubling)
  3. loading                 - V = max(0, C*R - D) * catchment_area
                               C: uniform runoff coefficient  (RUNOFF_C)
                               D: drainage-capacity assumption, mm removed
                                  over the event                (DRAIN_MM)
  4. spill cascade           - pools over capacity pass excess to the pool
                               their lowest adjacent outside cell drains to
                               (Barnes fill-spill-merge, simplified);
                               processed in topological order, cycles merged
                               conservatively (excess marked exported)

STILL TERRAIN SCREENING, NOT A FLOOD PREDICTION. No sewers/pipes (beyond the
uniform D assumption), no infiltration variation, no hydraulics, no timing.
C and D are stated assumptions, adjustable below.

Usage:
  scenario.py <dem.tif> <aoi.geojson> <water.geojson> <out_dir> <name>
Writes <out_dir>/<name>_depth_<sid>.tif per scenario (same conventions as
bluespot.py: float32 m, 0 = dry, nan = open water/nodata, cropped to AOI)
plus <out_dir>/<name>_scenarios.json (per-scenario stats for the viewer).
"""
import json, os, sys
from collections import deque
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from rasterio.warp import transform_geom
from rasterio.features import rasterize
from skimage.morphology import reconstruction
from skimage.measure import label

from bluespot import aoi_bounds, MIN_DEPTH

# ---- stated assumptions (documented in docs/MODEL.md + viewer sources) ----
RUNOFF_C = 0.55   # uniform runoff coefficient (dense urban residential mix)
DRAIN_MM = 10.0   # drainage capacity: mm of runoff removed per event by
                  # sewers/infiltration. An assumption, not data - the real
                  # network is not public. Adjust and re-run to test.

# Rainfall bookmarks. ISWS values verified 2026-08-17 (see data/SOURCES.md):
# Bulletin 70 (Huff & Angel 1989) NE Illinois 100-yr 24-hr = 7.58 in;
# Bulletin 75 (ISWS, March 2020) Section 2 (Northeast) 24-hr:
#   2-yr = 3.34 in, 100-yr = 8.57 in.
SCENARIOS = [
    # id, rain inches, short label, provenance
    ("r10",       1.00, "1.0″", "nuisance rain (reference, not a design storm)"),
    ("b75_2yr",   3.34, "3.34″", "Bulletin 75 2-yr 24-hr, NE Illinois"),
    ("b70_100yr", 7.58, "7.58″", "Bulletin 70 100-yr 24-hr (superseded 1989 standard)"),
    ("b75_100yr", 8.57, "8.57″", "Bulletin 75 100-yr 24-hr (current standard)"),
]

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


def fill_domain(dem_path, aoi_path, water_path, buffer_m=1000.0):
    """Same domain + fill as bluespot.py, but returns the full buffered-domain
    arrays instead of writing the cropped product."""
    with rasterio.open(dem_path) as src:
        x0, y0, x1, y1 = aoi_bounds(aoi_path, src.crs)
        win = from_bounds(x0 - buffer_m, y0 - buffer_m, x1 + buffer_m,
                          y1 + buffer_m, src.transform).round_offsets().round_lengths()
        win = win.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
        dem = src.read(1, window=win).astype("float64")
        transform = src.window_transform(win)
        nodata, crs, profile = src.nodata, src.crs, src.profile
        wgj = json.load(open(water_path))
        wgeoms = [transform_geom("EPSG:4326", crs, f["geometry"]) for f in wgj["features"]]
        water = rasterize(wgeoms, out_shape=dem.shape, transform=transform,
                          fill=0, default_value=1, dtype="uint8").astype(bool)
    valid = np.isfinite(dem)
    if nodata is not None:
        valid &= dem != nodata
    hi = float(dem[valid].max()) + 100.0
    dem_w = np.where(valid, dem, hi)
    seed = np.full_like(dem_w, hi)
    for sl in (np.s_[0, :], np.s_[-1, :], np.s_[:, 0], np.s_[:, -1]):
        seed[sl] = dem_w[sl]
    seed[water] = dem_w[water]
    filled = reconstruction(seed, dem_w, method="erosion")
    return dem_w, filled, valid, water, transform, crs, profile, (x0, y0, x1, y1)


def flow_routing(filled, valid, water, pool_mask):
    """D8 steepest descent on the filled DEM. Terminals: pool cells, water,
    invalid, and the domain border. Flats (no downhill neighbor) drain via
    equal-elevation neighbors that already drain (guaranteed to exist on a
    filled surface outside pools). Returns root cell index per cell."""
    H, W = filled.shape
    idx = np.arange(H * W, dtype=np.int64).reshape(H, W)
    F = np.where(valid, filled, np.inf)
    terminal = (~valid) | water | pool_mask
    terminal[0, :] = terminal[-1, :] = terminal[:, 0] = terminal[:, -1] = True

    ds = idx.copy()
    best = np.zeros((H, W))
    for dr, dc, dist in OFF:
        drop = (F - shift(F, dr, dc, np.inf)) / dist
        better = (~terminal) & (drop > best)
        if better.any():
            ds[better] = shift(idx, dr, dc, -1)[better]
            best[better] = drop[better]

    # flat resolution: adopt an equal-elevation neighbor that already drains
    resolved = terminal | (best > 0)
    pending = ~resolved
    for it in range(2000):
        progress = False
        for dr, dc, _ in OFF:
            take = pending & shift(resolved, dr, dc, False) & \
                   (shift(F, dr, dc, np.inf) == F)
            if take.any():
                ds[take] = shift(idx, dr, dc, -1)[take]
                resolved |= take
                pending &= ~take
                progress = True
        if not progress or not pending.any():
            break
    n_stuck = int(pending.sum())
    if n_stuck:
        print(f"  warning: {n_stuck} flat cells unresolved (treated as exported)")

    # pointer doubling to the terminal each cell drains to
    r = ds.reshape(-1)
    for _ in range(64):
        nxt = r[r]
        if np.array_equal(nxt, r):
            break
        r = nxt
    return r  # flat root index per cell


def spill_edges(lab, F, root_pool_flat, npools):
    """For each pool, the lowest valid adjacent outside cell that does NOT
    drain straight back into the pool; downstream = the pool (or export=0)
    that cell drains to. Returns (target[npools+1], spill_elev[npools+1])."""
    H, W = lab.shape
    idx = np.arange(H * W, dtype=np.int64).reshape(H, W)
    ps, cs, fs = [], [], []
    for dr, dc, _ in OFF:
        nb_lab = shift(lab, dr, dc, 0)
        m = (nb_lab > 0) & (nb_lab != lab) & np.isfinite(F)
        if m.any():
            ps.append(nb_lab[m]); cs.append(idx[m]); fs.append(F[m])
    ps = np.concatenate(ps); cs = np.concatenate(cs); fs = np.concatenate(fs)
    rp = root_pool_flat[cs]
    keep = rp != ps                      # exclude candidates draining back in
    ps, cs, fs, rp = ps[keep], cs[keep], fs[keep], rp[keep]
    order = np.lexsort((fs, ps))
    ps, fs, rp = ps[order], fs[order], rp[order]
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


def water_levels(stored, cap, pour, lab_flat, z_flat, cell_area, shape):
    """Per-cell scenario depth from per-pool stored volume via exact
    stage-storage (cells submerge bottom-up)."""
    depth = np.zeros(lab_flat.shape, dtype="float32")
    cells = np.flatnonzero(lab_flat > 0)
    pl = lab_flat[cells]; z = z_flat[cells]
    order = np.lexsort((z, pl))
    cells, pl, z = cells[order], pl[order], z[order]
    npools = len(cap) - 1
    starts = np.searchsorted(pl, np.arange(1, npools + 2))
    for p in np.flatnonzero(stored > 0):
        s, e = starts[p - 1], starts[p]
        zs = z[s:e]
        V = stored[p] / cell_area
        if V >= (cap[p] / cell_area) - 1e-9:
            w = pour[p]
        else:
            S = np.cumsum(zs)
            j = np.arange(1, len(zs))
            need = j * zs[1:] - S[:-1]          # volume to raise surface to zs[j]
            m = int(np.searchsorted(need, V, side="right"))
            w = (V + S[m]) / (m + 1)
        depth[cells[s:e]] = np.maximum(w - zs, 0.0)
    return depth.reshape(shape)


def main(dem_path, aoi_path, water_path, out_dir, name):
    os.makedirs(out_dir, exist_ok=True)
    print("fill...")
    dem_w, filled, valid, water, transform, crs, profile, bounds = \
        fill_domain(dem_path, aoi_path, water_path)
    cell_area = abs(transform.a * transform.e)
    depth_full = filled - dem_w
    pool_mask = valid & ~water & (depth_full >= MIN_DEPTH)

    print("pools...")
    lab = label(pool_mask, connectivity=2).astype(np.int64)
    npools = int(lab.max())
    lab_flat = lab.reshape(-1)
    pool_sel = lab_flat > 0
    cap = np.bincount(lab_flat[pool_sel], weights=depth_full.reshape(-1)[pool_sel],
                      minlength=npools + 1) * cell_area
    pour = np.zeros(npools + 1)
    pour[lab_flat[pool_sel]] = filled.reshape(-1)[pool_sel]
    print(f"  {npools:,} pools, capacity {cap.sum():,.0f} m3")

    print("D8 routing + catchments...")
    root = flow_routing(filled, valid, water, pool_mask)
    root_pool = lab_flat[root]                       # 0 = water/edge/export
    contrib = valid.reshape(-1)
    catch_area = np.bincount(root_pool[contrib], minlength=npools + 1) * cell_area
    print(f"  catchment: {catch_area[1:].sum():,.0f} m2 to pools, "
          f"{catch_area[0]:,.0f} m2 drains to water/edge")

    print("spill edges...")
    F = np.where(valid, filled, np.inf)
    target, spill_elev = spill_edges(lab, F, root_pool, npools)

    # crop window (same convention as bluespot.py)
    x0, y0, x1, y1 = bounds
    cwin = from_bounds(x0, y0, x1, y1, transform).round_offsets().round_lengths()
    r0, c0 = int(cwin.row_off), int(cwin.col_off)
    rh, cw = int(cwin.height), int(cwin.width)
    out_transform = rasterio.transform.Affine(
        transform.a, transform.b, transform.c + c0 * transform.a,
        transform.d, transform.e, transform.f + r0 * transform.e)
    profile.update(height=rh, width=cw, transform=out_transform, dtype="float32",
                   nodata=np.nan, compress="deflate", predictor=2, count=1,
                   driver="GTiff")
    nan_mask = (~valid) | water

    meta = {"assumptions": {"runoff_c": RUNOFF_C, "drain_mm": DRAIN_MM,
            "note": "terrain screening, not a flood prediction; C and D are "
                    "stated assumptions (pipeline/scenario.py)"},
            "scenarios": []}
    for sid, inches, short, prov in SCENARIOS:
        rain_mm = inches * 25.4
        net_mm = max(0.0, RUNOFF_C * rain_mm - DRAIN_MM)
        load = (net_mm / 1000.0) * catch_area
        load[0] = 0.0
        stored, exported = cascade(load, cap, target, pour)
        d = water_levels(stored, cap, pour, lab_flat, dem_w.reshape(-1),
                         cell_area, filled.shape)
        d[d < MIN_DEPTH] = 0.0
        d[nan_mask] = np.nan
        dc = d[r0:r0 + rh, c0:c0 + cw]
        with rasterio.open(os.path.join(out_dir, f"{name}_depth_{sid}.tif"),
                           "w", **profile) as dst:
            dst.write(dc, 1)
        fin = np.isfinite(dc); wet = fin & (dc > 0)
        wet_pct = 100.0 * wet.sum() / fin.sum()
        full_n = int(np.sum(stored[1:] >= cap[1:] - 1e-9))
        rec = {"id": sid, "rain_in": inches, "rain_mm": round(rain_mm, 1),
               "label": short, "provenance": prov,
               "wet_pct": round(float(wet_pct), 2),
               "stored_m3": round(float(stored[1:].sum())),
               "exported_m3": round(float(exported)),
               "pools_at_capacity": full_n}
        meta["scenarios"].append(rec)
        print(f"  {sid:>10}: rain {inches:.2f} in | net {net_mm:5.1f} mm | "
              f"wet {wet_pct:4.1f}% | stored {stored[1:].sum():>12,.0f} m3 | "
              f"exported {exported:>12,.0f} m3 | full pools {full_n:,}/{npools:,}")

    # the static full-fill layer is the max scenario; report it for the UI
    dfc = np.where(nan_mask, np.nan, depth_full.astype("float32"))
    dfc[dfc < MIN_DEPTH] = 0.0
    dfc = dfc[r0:r0 + rh, c0:c0 + cw]
    fin = np.isfinite(dfc); wet = fin & (dfc > 0)
    meta["scenarios"].append({
        "id": "full", "rain_in": None, "rain_mm": None, "label": "max",
        "provenance": "full fill — static upper envelope, every pool at capacity",
        "wet_pct": round(float(100.0 * wet.sum() / fin.sum()), 2),
        "stored_m3": round(float(cap.sum())), "exported_m3": None,
        "pools_at_capacity": npools})
    out_json = os.path.join(out_dir, f"{name}_scenarios.json")
    json.dump(meta, open(out_json, "w"), indent=1)
    print(f"-> {out_json}")


if __name__ == "__main__":
    main(*sys.argv[1:6])
