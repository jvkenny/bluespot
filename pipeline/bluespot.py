#!/usr/bin/env python3
"""Bluespot terrain screening: fill all depressions in a DEM, difference
against raw terrain. Residual = max ponding depth when local drainage is
overwhelmed. TERRAIN SCREENING ONLY - not a hydraulic flood model.

Method: morphological reconstruction by erosion (Vincent 1993) — equivalent
to priority-flood depression filling. Outlets are (a) the edges of a buffered
compute domain and (b) open-water cells (rivers and the lake drain the basin
even where bridge decks in the DEM would otherwise dam the channel).

Two entry points:

Small AOI (single raster fits in RAM), unchanged from v0:
  bluespot.py <dem.tif> <aoi.geojson> <water.geojson> <out_prefix> [buffer_m]
  Writes <out_prefix>_depth.tif (float32 m, 0 = dry, nan = open water/nodata)

Citywide (per-DEM-tile chunks with a halo, then a merged COG):
  bluespot.py --chunked <dem_dir> <aoi.geojson> <water.geojson> <out_dir> \
              <out_cog.tif> [halo_m]
  Each USGS 10 km tile becomes one chunk: its core extent plus a <halo_m>
  (default 1000 m) halo is read from a VRT mosaic of all tiles, filled with
  water cells + halo edges as outlets, cropped back to the core, masked to
  the AOI polygon, and written to <out_dir>. Chunks are then mosaicked
  (gdalbuildvrt) and translated to a compressed COG at <out_cog.tif>.
  Peak memory stays bounded by the chunk size (~12k x 12k float32),
  regardless of total mosaic size. Trade-off: a depression that extends
  more than halo_m beyond a tile edge sees an artificial outlet at the halo
  boundary, so depths in multi-kilometre pools can differ slightly from a
  single-domain fill (see docs/METHOD.md).
"""
import glob, json, os, resource, subprocess, sys, time
import numpy as np
import rasterio
from rasterio.windows import from_bounds, Window
from rasterio.warp import transform_geom
from rasterio.features import rasterize
from skimage.morphology import reconstruction

MIN_DEPTH = 0.05  # m; below = noise
GDAL = "/opt/homebrew/bin"


def load_geoms(path, dst_crs):
    gj = json.load(open(path))
    return [transform_geom("EPSG:4326", dst_crs, f["geometry"])
            for f in gj["features"]]


def geom_bounds(geoms):
    xs, ys = [], []
    def walk(c):
        if isinstance(c[0], (int, float)): xs.append(c[0]); ys.append(c[1])
        else:
            for k in c: walk(k)
    for g in geoms: walk(g["coordinates"])
    return min(xs), min(ys), max(xs), max(ys)


def compute_depth(dem, valid, water, min_depth=MIN_DEPTH):
    """Fill depressions (outlets: array edges + water cells), return depth.
    dem: float32 2D; valid: bool; water: bool. Depth is nan on invalid/water."""
    hi = np.float32(dem[valid].max() + 100.0)
    dem_w = np.where(valid, dem, hi).astype("float32")
    seed = np.full_like(dem_w, hi)
    for sl in (np.s_[0, :], np.s_[-1, :], np.s_[:, 0], np.s_[:, -1]):
        seed[sl] = dem_w[sl]
    seed[water] = dem_w[water]          # open water drains
    filled = reconstruction(seed, dem_w, method="erosion").astype("float32")
    depth = filled - dem_w
    del filled, seed, dem_w
    depth[depth < min_depth] = 0.0
    depth[~valid | water] = np.nan      # water itself is not a "pool"
    return depth


def main(dem_path, aoi_path, water_path, out_prefix, buffer_m=1000.0):
    """v0 single-domain entry point for small AOIs."""
    buffer_m = float(buffer_m)
    with rasterio.open(dem_path) as src:
        x0, y0, x1, y1 = geom_bounds(load_geoms(aoi_path, src.crs))
        win = from_bounds(x0 - buffer_m, y0 - buffer_m, x1 + buffer_m, y1 + buffer_m,
                          src.transform).round_offsets().round_lengths()
        win = win.intersection(Window(0, 0, src.width, src.height))
        dem = src.read(1, window=win).astype("float32")
        transform = src.window_transform(win)
        nodata, crs, profile = src.nodata, src.crs, src.profile
        wgeoms = load_geoms(water_path, crs)
        water = rasterize(wgeoms, out_shape=dem.shape, transform=transform,
                          fill=0, default_value=1, dtype="uint8").astype(bool)
    valid = np.isfinite(dem)
    if nodata is not None:
        valid &= dem != nodata
    depth = compute_depth(dem, valid, water)
    # crop buffer off: back to AOI bounds
    cwin = from_bounds(x0, y0, x1, y1, transform).round_offsets().round_lengths()
    r0, c0 = int(cwin.row_off), int(cwin.col_off)
    depth = depth[r0:r0 + int(cwin.height), c0:c0 + int(cwin.width)]
    out_transform = rasterio.transform.Affine(transform.a, transform.b,
        transform.c + c0 * transform.a, transform.d, transform.e,
        transform.f + r0 * transform.e)
    profile.update(height=depth.shape[0], width=depth.shape[1],
                   transform=out_transform, dtype="float32", nodata=np.nan,
                   compress="deflate", predictor=2, count=1, driver="GTiff")
    with rasterio.open(f"{out_prefix}_depth.tif", "w", **profile) as dst:
        dst.write(depth, 1)
    fin = np.isfinite(depth); wet = fin & (depth > 0)
    print(f"cells: {fin.sum():,} | wet: {wet.sum():,} ({100*wet.sum()/fin.sum():.1f}%) "
          f"| max depth: {np.nanmax(depth):.2f} m")


def _core_bounds(path):
    """A USGS 1m tile's authoritative 10 km extent, shedding the 6 m collar
    (bounds land within 10 m of a 1 km grid line; snap to it)."""
    with rasterio.open(path) as t:
        b = t.bounds
    def snap(v):
        r = round(v / 1000.0) * 1000.0
        return r if abs(v - r) <= 10 else v
    return snap(b.left), snap(b.bottom), snap(b.right), snap(b.top)


def chunked(dem_dir, aoi_path, water_path, out_dir, out_cog, halo_m=1000.0):
    halo_m = float(halo_m)
    tiles = sorted(os.path.abspath(t)
                   for t in glob.glob(os.path.join(dem_dir, "*.tif")))
    if not tiles:
        sys.exit(f"no .tif in {dem_dir}")
    os.makedirs(out_dir, exist_ok=True)
    vrt = os.path.join(out_dir, "dem_mosaic.vrt")
    subprocess.run([f"{GDAL}/gdalbuildvrt", "-q", vrt] + tiles, check=True)
    with rasterio.open(vrt) as src:
        crs, nodata = src.crs, src.nodata
    print(f"{len(tiles)} DEM tiles, CRS {crs}, nodata {nodata}")
    wgeoms = load_geoms(water_path, crs)
    ageoms = load_geoms(aoi_path, crs)

    tot_valid = tot_wet = 0
    max_d, max_xy = 0.0, None
    t_all = time.time()
    with rasterio.open(vrt) as src:
        for tp in tiles:
            name = os.path.basename(tp).replace(".tif", "")
            outp = os.path.join(out_dir, f"depth_{name}.tif")
            cx0, cy0, cx1, cy1 = _core_bounds(tp)
            win = from_bounds(cx0 - halo_m, cy0 - halo_m, cx1 + halo_m,
                              cy1 + halo_m, src.transform
                              ).round_offsets().round_lengths()
            win = win.intersection(Window(0, 0, src.width, src.height))
            transform = src.window_transform(win)
            shape = (int(win.height), int(win.width))
            aoi_mask = rasterize(ageoms, out_shape=shape, transform=transform,
                                 fill=0, default_value=1, dtype="uint8").astype(bool)
            if not aoi_mask.any():
                print(f"{name}: outside AOI, skipped"); continue
            if os.path.exists(outp):
                with rasterio.open(outp) as d:
                    depth = d.read(1)
                print(f"{name}: exists, reusing")
            else:
                t0 = time.time()
                dem = src.read(1, window=win).astype("float32")
                valid = np.isfinite(dem)
                if nodata is not None:
                    valid &= dem != nodata
                if not valid.any():
                    print(f"{name}: all nodata, skipped"); continue
                water = rasterize(wgeoms, out_shape=shape, transform=transform,
                                  fill=0, default_value=1, dtype="uint8").astype(bool)
                depth = compute_depth(dem, valid, water)
                del dem, valid, water
                depth[~aoi_mask] = np.nan   # product is masked to the AOI
                # crop halo off: back to tile core
                cwin = from_bounds(cx0, cy0, cx1, cy1, transform
                                   ).round_offsets().round_lengths()
                cwin = cwin.intersection(Window(0, 0, shape[1], shape[0]))
                r0, c0 = int(cwin.row_off), int(cwin.col_off)
                depth = depth[r0:r0 + int(cwin.height), c0:c0 + int(cwin.width)]
                out_transform = rasterio.transform.Affine(
                    transform.a, transform.b, transform.c + c0 * transform.a,
                    transform.d, transform.e, transform.f + r0 * transform.e)
                if not np.isfinite(depth).any():
                    print(f"{name}: no valid land in AOI, skipped"); continue
                with rasterio.open(outp, "w", driver="GTiff", count=1,
                        dtype="float32", crs=crs, transform=out_transform,
                        height=depth.shape[0], width=depth.shape[1],
                        nodata=np.nan, compress="deflate", predictor=2,
                        tiled=True) as dst:
                    dst.write(depth, 1)
                rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**30
                print(f"{name}: {time.time()-t0:.0f}s, peak RSS {rss:.1f} GB", end="")
            fin = np.isfinite(depth); wet = fin & (depth > 0)
            tot_valid += int(fin.sum()); tot_wet += int(wet.sum())
            if wet.any():
                d = float(np.nanmax(depth))
                if d > max_d:
                    with rasterio.open(outp) as o:
                        k = np.unravel_index(np.nanargmax(depth), depth.shape)
                        max_d, max_xy = d, rasterio.transform.xy(o.transform, *k)
            print(f"  wet {100*wet.sum()/max(fin.sum(),1):.1f}% of tile land")
            del depth

    print(f"\nfill stage: {time.time()-t_all:.0f}s | AOI land cells {tot_valid:,} "
          f"| wet {tot_wet:,} ({100*tot_wet/max(tot_valid,1):.2f}%) "
          f"| max {max_d:.2f} m at {max_xy}")
    chunks = sorted(glob.glob(os.path.join(out_dir, "depth_*.tif")))
    mvrt = os.path.join(out_dir, "depth_mosaic.vrt")
    subprocess.run([f"{GDAL}/gdalbuildvrt", "-q", mvrt] + chunks, check=True)
    subprocess.run([f"{GDAL}/gdal_translate", "-q", "-of", "COG",
                    "-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=3",
                    "-co", "NUM_THREADS=ALL_CPUS", "-co", "BIGTIFF=IF_SAFER",
                    mvrt, out_cog], check=True)
    print(f"COG -> {out_cog} ({os.path.getsize(out_cog)/2**20:.0f} MB)")
    with open(os.path.join(out_dir, "stats.json"), "w") as f:
        json.dump({"aoi_land_cells": tot_valid, "wet_cells": tot_wet,
                   "wet_pct": 100 * tot_wet / max(tot_valid, 1),
                   "max_depth_m": max_d, "max_depth_xy": max_xy}, f, indent=1)


if __name__ == "__main__":
    if sys.argv[1] == "--chunked":
        chunked(*sys.argv[2:8])
    else:
        main(*sys.argv[1:6])
