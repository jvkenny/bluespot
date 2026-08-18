#!/bin/zsh
# Terrain "why" underlay: multidirectional hillshade blended with a muted
# hypsometric tint of the DEM, tiled for the viewer.
# Usage: pipeline/make_terrain.sh <raw_dem.tif> <ulx> <uly> <lrx> <lry> <out_tiles_dir>
set -e
DEM=$1; OUT=$6
DIR=$(mktemp -d)
gdal_translate -q -projwin $2 $3 $4 $5 $DEM $DIR/aoi.tif
gdaldem hillshade -q -multidirectional -compute_edges $DIR/aoi.tif $DIR/hs.tif
cat > $DIR/tint.txt <<RAMP
172 138 152 134
177 172 181 155
180 208 204 176
183 224 213 185
186 222 202 168
190 210 186 150
195 193 168 133
RAMP
gdaldem color-relief -q $DIR/aoi.tif $DIR/tint.txt $DIR/tint.tif
python3 - "$DIR" <<'PY'
import sys, numpy as np
from osgeo import gdal
d = sys.argv[1]
hs = gdal.Open(f"{d}/hs.tif").ReadAsArray().astype("float64") / 255.0
t = gdal.Open(f"{d}/tint.tif")
tint = t.ReadAsArray().astype("float64")          # (3,h,w)
blend = tint * (0.30 + 0.70 * hs)                  # multiply, lifted shadows
drv = gdal.GetDriverByName("GTiff")
o = drv.Create(f"{d}/blend.tif", t.RasterXSize, t.RasterYSize, 3, gdal.GDT_Byte)
o.SetGeoTransform(t.GetGeoTransform()); o.SetProjection(t.GetProjection())
for i in range(3):
    o.GetRasterBand(i+1).WriteArray(np.clip(blend[i], 0, 255).astype("uint8"))
o.FlushCache()
PY
rm -rf $OUT; mkdir -p $OUT
gdal2tiles.py -q -z 11-17 --xyz -r bilinear -w none --processes=8 $DIR/blend.tif $OUT
rm -rf $DIR
echo "terrain tiles -> $OUT"
