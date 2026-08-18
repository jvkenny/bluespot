#!/usr/bin/env python3
"""Region-scale bluespot fill: one OS process per 10 km chunk.

bluespot.py --chunked already chunks the fill by DEM tile, but it does every
chunk inside ONE python process. Over the 18-tile city that was fine; over
124 regional tiles it is not — the citywide run's RSS crept from ~4 GB to
9.2 GB because freed numpy blocks are retained by the allocator (and
skimage's reconstruction leaves large transient arrays). Running each chunk
in its own subprocess returns every byte to the OS at chunk exit, so peak
system memory is one chunk's worth no matter how many chunks there are — and
it lets several chunks run concurrently on purpose rather than by accident.

Differences from bluespot.py --chunked, all of them scale-driven:
- one subprocess per chunk, <workers> at a time
- water geometries are bbox-filtered to the chunk before rasterizing (the
  regional OSM water file has ~50k polygons; rasterizing all of them into
  every one of 124 chunk windows is pure waste)
- a CRS precheck, because the region draws on several lidar projects and
  gdalbuildvrt silently requires one common projection
- per-chunk stats land in <out_dir>/chunkstats/, so an interrupted run
  resumes without recomputing or losing the totals

Fill semantics (outlets, min depth, AOI masking, halo cropping) are imported
unchanged from bluespot.py — this file is about process structure, not method.

Usage:
  driver: bluespot_region.py <dem_dir> <aoi.geojson> <water.geojson> \
              <out_dir> <out_cog.tif> [halo_m] [workers]
  worker: bluespot_region.py --chunk <vrt> <tile.tif> <aoi> <water> \
              <out.tif> <stats.json> <halo_m>
"""
import glob, json, os, resource, subprocess, sys, time
import numpy as np
import rasterio
from rasterio.windows import from_bounds, Window
from rasterio.warp import transform_geom, transform_bounds
from rasterio.features import rasterize

from bluespot import compute_depth, _core_bounds, GDAL


def _bbox(geom):
    xs, ys = [], []
    def walk(c):
        if isinstance(c[0], (int, float)): xs.append(c[0]); ys.append(c[1])
        else:
            for k in c: walk(k)
    walk(geom["coordinates"])
    return min(xs), min(ys), max(xs), max(ys)


def load_geoms_bbox(path, dst_crs, bounds4326):
    """Load GeoJSON features whose bbox meets bounds4326, in dst_crs."""
    w, s, e, n = bounds4326
    out = []
    for f in json.load(open(path))["features"]:
        g = f["geometry"]
        if not g:
            continue
        x0, y0, x1, y1 = _bbox(g)
        if x1 < w or x0 > e or y1 < s or y0 > n:
            continue
        out.append(transform_geom("EPSG:4326", dst_crs, g))
    return out


# ---------------------------------------------------------------- worker ---
def chunk_worker(vrt, tile, aoi_path, water_path, outp, statsp, halo_m):
    halo_m = float(halo_m)
    t0 = time.time()
    cx0, cy0, cx1, cy1 = _core_bounds(tile)
    with rasterio.open(vrt) as src:
        crs, nodata = src.crs, src.nodata
        win = from_bounds(cx0 - halo_m, cy0 - halo_m, cx1 + halo_m, cy1 + halo_m,
                          src.transform).round_offsets().round_lengths()
        win = win.intersection(Window(0, 0, src.width, src.height))
        transform = src.window_transform(win)
        shape = (int(win.height), int(win.width))
        b4326 = transform_bounds(crs, "EPSG:4326",
                                 *rasterio.windows.bounds(win, src.transform))
        ageoms = load_geoms_bbox(aoi_path, crs, b4326)
        if not ageoms:
            json.dump({"skipped": "outside AOI"}, open(statsp, "w")); return
        aoi_mask = rasterize(ageoms, out_shape=shape, transform=transform,
                             fill=0, default_value=1, dtype="uint8").astype(bool)
        if not aoi_mask.any():
            json.dump({"skipped": "outside AOI"}, open(statsp, "w")); return
        dem = src.read(1, window=win).astype("float32")

    valid = np.isfinite(dem)
    if nodata is not None:
        valid &= dem != nodata
    if not valid.any():
        json.dump({"skipped": "all nodata"}, open(statsp, "w")); return
    wgeoms = load_geoms_bbox(water_path, crs, b4326)
    water = (rasterize(wgeoms, out_shape=shape, transform=transform, fill=0,
                       default_value=1, dtype="uint8").astype(bool)
             if wgeoms else np.zeros(shape, bool))
    depth = compute_depth(dem, valid, water)
    del dem, valid, water
    depth[~aoi_mask] = np.nan
    del aoi_mask

    cwin = from_bounds(cx0, cy0, cx1, cy1, transform).round_offsets().round_lengths()
    cwin = cwin.intersection(Window(0, 0, shape[1], shape[0]))
    r0, c0 = int(cwin.row_off), int(cwin.col_off)
    depth = depth[r0:r0 + int(cwin.height), c0:c0 + int(cwin.width)]
    if not np.isfinite(depth).any():
        json.dump({"skipped": "no valid land in AOI"}, open(statsp, "w")); return
    out_transform = rasterio.transform.Affine(
        transform.a, transform.b, transform.c + c0 * transform.a,
        transform.d, transform.e, transform.f + r0 * transform.e)
    with rasterio.open(outp + ".part", "w", driver="GTiff", count=1,
            dtype="float32", crs=crs, transform=out_transform,
            height=depth.shape[0], width=depth.shape[1], nodata=np.nan,
            compress="deflate", predictor=2, tiled=True) as dst:
        dst.write(depth, 1)
    os.replace(outp + ".part", outp)

    fin = np.isfinite(depth); wet = fin & (depth > 0)
    st = {"tile": os.path.basename(tile), "valid": int(fin.sum()),
          "wet": int(wet.sum()), "secs": round(time.time() - t0, 1),
          "peak_rss_gb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**30, 2)}
    if wet.any():
        k = np.unravel_index(np.nanargmax(depth), depth.shape)
        st["max_depth_m"] = round(float(depth[k]), 3)
        st["max_xy"] = list(rasterio.transform.xy(out_transform, *k))
    json.dump(st, open(statsp, "w"))


# ---------------------------------------------------------------- driver ---
def crs_precheck(tiles):
    """gdalbuildvrt needs one common projection; the region spans several
    lidar projects, so verify rather than discover it at merge time."""
    seen = {}
    for t in tiles:
        with rasterio.open(t) as s:
            seen.setdefault(str(s.crs), []).append(os.path.basename(t))
    for c, ts in sorted(seen.items(), key=lambda x: -len(x[1])):
        print(f"  CRS {c}: {len(ts)} tiles")
    if len(seen) > 1:
        odd = sorted(seen.items(), key=lambda x: -len(x[1]))[1:]
        sys.exit("mixed CRS; warp these to the majority CRS first: "
                 + ", ".join(f for _, ts in odd for f in ts[:8]))
    return list(seen)[0]


def driver(dem_dir, aoi_path, water_path, out_dir, out_cog, halo_m=1000.0,
           workers=3):
    workers = int(workers)
    t_all = time.time()
    tiles = sorted(os.path.abspath(t) for t in glob.glob(os.path.join(dem_dir, "*.tif")))
    if not tiles:
        sys.exit(f"no .tif in {dem_dir}")
    os.makedirs(out_dir, exist_ok=True)
    sdir = os.path.join(out_dir, "chunkstats"); os.makedirs(sdir, exist_ok=True)
    print(f"{len(tiles)} DEM tiles; CRS precheck:")
    crs_precheck(tiles)
    vrt = os.path.join(out_dir, "dem_mosaic.vrt")
    subprocess.run([f"{GDAL}/gdalbuildvrt", "-q", "-overwrite", vrt] + tiles, check=True)
    print(f"VRT -> {vrt}\nfilling with {workers} concurrent chunk processes, "
          f"halo {halo_m} m", flush=True)

    me = os.path.abspath(__file__)
    py = sys.executable
    jobs, running, done = [], [], 0
    for t in tiles:
        name = os.path.basename(t).replace(".tif", "")
        jobs.append((t, os.path.join(out_dir, f"depth_{name}.tif"),
                     os.path.join(sdir, f"{name}.json")))
    todo = [j for j in jobs if not os.path.exists(j[2])]
    print(f"{len(jobs) - len(todo)} chunks already done, {len(todo)} to run", flush=True)

    t_fill = time.time()
    while todo or running:
        while todo and len(running) < workers:
            t, outp, statsp = todo.pop(0)
            p = subprocess.Popen([py, me, "--chunk", vrt, t, aoi_path,
                                  water_path, outp, statsp, str(halo_m)],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            running.append((p, t, statsp))
        time.sleep(2)
        for r in running[:]:
            p, t, statsp = r
            if p.poll() is None:
                continue
            running.remove(r)
            done += 1
            out = p.stdout.read().decode().strip()
            nm = os.path.basename(t)
            if p.returncode != 0:
                print(f"  [{done}/{len(jobs)}] FAILED {nm} rc={p.returncode}\n{out}",
                      flush=True)
                continue
            try:
                st = json.load(open(statsp))
            except Exception:
                print(f"  [{done}/{len(jobs)}] {nm}: no stats", flush=True); continue
            if "skipped" in st:
                print(f"  [{done}/{len(jobs)}] {nm}: {st['skipped']}", flush=True)
            else:
                pct = 100 * st["wet"] / max(st["valid"], 1)
                print(f"  [{done}/{len(jobs)}] {nm}: {st['secs']:.0f}s "
                      f"RSS {st['peak_rss_gb']:.1f}GB wet {pct:.1f}%", flush=True)
    print(f"\nfill stage: {time.time() - t_fill:.0f}s", flush=True)

    tot_v = tot_w = 0; max_d = 0.0; max_xy = None
    for f in sorted(glob.glob(os.path.join(sdir, "*.json"))):
        st = json.load(open(f))
        if "skipped" in st:
            continue
        tot_v += st["valid"]; tot_w += st["wet"]
        if st.get("max_depth_m", 0) > max_d:
            max_d, max_xy = st["max_depth_m"], st.get("max_xy")
    print(f"AOI land cells {tot_v:,} | wet {tot_w:,} "
          f"({100*tot_w/max(tot_v,1):.2f}%) | max {max_d:.2f} m at {max_xy}")

    chunks = sorted(glob.glob(os.path.join(out_dir, "depth_*.tif")))
    print(f"merging {len(chunks)} chunk rasters -> COG", flush=True)
    mvrt = os.path.join(out_dir, "depth_mosaic.vrt")
    subprocess.run([f"{GDAL}/gdalbuildvrt", "-q", "-overwrite", mvrt] + chunks, check=True)
    t_cog = time.time()
    subprocess.run([f"{GDAL}/gdal_translate", "-of", "COG",
                    "-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=3",
                    "-co", "NUM_THREADS=ALL_CPUS", "-co", "BIGTIFF=YES",
                    mvrt, out_cog], check=True)
    print(f"COG -> {out_cog} ({os.path.getsize(out_cog)/2**30:.2f} GB) "
          f"in {time.time()-t_cog:.0f}s")
    json.dump({"aoi_land_cells": tot_v, "wet_cells": tot_w,
               "wet_pct": 100 * tot_w / max(tot_v, 1), "max_depth_m": max_d,
               "max_depth_xy": max_xy, "chunks": len(chunks),
               "halo_m": float(halo_m),
               "total_secs": round(time.time() - t_all)},
              open(os.path.join(out_dir, "stats.json"), "w"), indent=1)
    print(f"total {time.time() - t_all:.0f}s")


if __name__ == "__main__":
    if sys.argv[1] == "--chunk":
        chunk_worker(*sys.argv[2:9])
    else:
        driver(*sys.argv[1:8])
