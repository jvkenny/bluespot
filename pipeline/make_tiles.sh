#!/bin/zsh
# Colorize bluespot depth raster and cut XYZ web tiles for the viewer.
# Usage: pipeline/make_tiles.sh data/derived/north-side-pilot_depth.tif viewer/tiles/depth
set -e
DEPTH=$1; OUT=$2
DIR=$(mktemp -d)
cat > $DIR/ramp.txt <<RAMP
nv 0 0 0 0
0.0 0 0 0 0
0.049 0 0 0 0
0.05 198 219 239 140
0.15 158 202 225 165
0.3 107 174 214 190
0.5 49 130 189 215
1.0 8 81 156 235
3.5 8 48 107 255
RAMP
gdaldem color-relief $DEPTH $DIR/ramp.txt $DIR/rgba.tif -alpha -nearest_color_entry
rm -rf $OUT; mkdir -p $OUT
gdal2tiles.py -q -z 11-17 --xyz -r bilinear -w none --processes=8 $DIR/rgba.tif $OUT
rm -rf $DIR
echo "tiles -> $OUT"
