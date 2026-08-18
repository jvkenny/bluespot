#!/usr/bin/env python3
"""Bluespot terrain screening: fill all depressions in a DEM, difference
against raw terrain. Residual = max ponding depth when local drainage is
overwhelmed. TERRAIN SCREENING ONLY - not a hydraulic flood model.

Method: morphological reconstruction by erosion (Vincent 1993) — equivalent
to priority-flood depression filling. Outlets are (a) the edges of a buffered
compute domain and (b) open-water cells (rivers drain the basin even where
bridge decks in the DEM would otherwise dam the channel). Result is cropped
back to the AOI so buffer-edge artifacts fall outside the product.

Usage: bluespot.py <dem.tif> <aoi.geojson> <water.geojson> <out_prefix> [buffer_m]
Writes <out_prefix>_depth.tif (float32 m, 0 = dry, nan = open water/nodata)
"""
import json, sys
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from rasterio.warp import transform_geom
from rasterio.features import rasterize
from skimage.morphology import reconstruction

MIN_DEPTH = 0.05  # m; below = noise

def aoi_bounds(path, crs):
    gj = json.load(open(path))
    geoms = [transform_geom("EPSG:4326", crs, f["geometry"]) for f in gj["features"]]
    xs, ys = [], []
    def walk(c):
        if isinstance(c[0], (int, float)): xs.append(c[0]); ys.append(c[1])
        else:
            for k in c: walk(k)
    for g in geoms: walk(g["coordinates"])
    return min(xs), min(ys), max(xs), max(ys)

def main(dem_path, aoi_path, water_path, out_prefix, buffer_m=1000.0):
    buffer_m = float(buffer_m)
    with rasterio.open(dem_path) as src:
        x0, y0, x1, y1 = aoi_bounds(aoi_path, src.crs)
        win = from_bounds(x0 - buffer_m, y0 - buffer_m, x1 + buffer_m, y1 + buffer_m,
                          src.transform).round_offsets().round_lengths()
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
    seed[water] = dem_w[water]          # open water drains
    filled = reconstruction(seed, dem_w, method="erosion")
    depth = (filled - dem_w).astype("float32")
    depth[depth < MIN_DEPTH] = 0.0
    depth[~valid | water] = np.nan      # water itself is not a "pool"
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

if __name__ == "__main__":
    main(*sys.argv[1:])
