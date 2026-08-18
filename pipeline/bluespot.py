#!/usr/bin/env python3
"""Bluespot terrain screening: fill all depressions in a DEM, difference
against raw terrain. Residual = max ponding depth when local drainage is
overwhelmed. TERRAIN SCREENING ONLY - not a hydraulic flood model.

Method: morphological reconstruction by erosion (Vincent 1993), the classic
depression-filling operator; edges act as outlets. Equivalent to
priority-flood fill with no minimum slope.

Usage: bluespot.py <dem.tif> <aoi.geojson> <out_prefix>
Writes <out_prefix>_depth.tif  (float32, meters of ponding, 0 = dry)
       <out_prefix>_filled.tif (filled DEM, for QA)
"""
import json, sys
import numpy as np
import rasterio
from rasterio.mask import mask as rio_mask
from rasterio.warp import transform_geom
from skimage.morphology import reconstruction

MIN_DEPTH = 0.05  # meters; below this = noise, set to 0

def main(dem_path, aoi_path, out_prefix):
    gj = json.load(open(aoi_path))
    with rasterio.open(dem_path) as src:
        geoms = [transform_geom("EPSG:4326", src.crs, f["geometry"])
                 for f in gj["features"]]
        dem, transform = rio_mask(src, geoms, crop=True, nodata=src.nodata)
        dem = dem[0].astype("float64")
        nodata = src.nodata
        profile = src.profile
    valid = np.isfinite(dem)
    if nodata is not None:
        valid &= dem != nodata
    hi = float(dem[valid].max()) + 100.0
    dem_w = np.where(valid, dem, hi)  # nodata as high wall, ignored later
    # seed: interior raised to +inf equivalent, edges = terrain (outlets)
    seed = np.full_like(dem_w, hi)
    seed[0, :], seed[-1, :], seed[:, 0], seed[:, -1] = \
        dem_w[0, :], dem_w[-1, :], dem_w[:, 0], dem_w[:, -1]
    filled = reconstruction(seed, dem_w, method="erosion")
    depth = np.where(valid, filled - dem_w, np.nan).astype("float32")
    depth[depth < MIN_DEPTH] = 0.0
    profile.update(height=dem.shape[0], width=dem.shape[1],
                   transform=transform, dtype="float32", nodata=np.nan,
                   compress="deflate", predictor=2, count=1)
    with rasterio.open(f"{out_prefix}_depth.tif", "w", **profile) as dst:
        dst.write(depth, 1)
    with rasterio.open(f"{out_prefix}_filled.tif", "w", **profile) as dst:
        dst.write(np.where(valid, filled, np.nan).astype("float32"), 1)
    wet = depth > 0
    print(f"cells: {valid.sum():,} | wet: {wet.sum():,} "
          f"({100*wet.sum()/valid.sum():.1f}%) | max depth: {np.nanmax(depth):.2f} m")

if __name__ == "__main__":
    main(*sys.argv[1:4])
