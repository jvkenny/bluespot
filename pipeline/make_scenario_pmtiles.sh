#!/bin/zsh
# Rain-scenario web tiles as PMTiles archives, one per design-storm bookmark.
#
# Same colour ramp, zoom range and encoding as the static depth archive in
# make_pmtiles.sh — the ramp MUST match so that a given ponding depth is the
# same blue on every stop of the viewer's "how much rain?" control; only the
# wet extent should change as the user moves between bookmarks.
#
#   PNG, not WEBP: GDAL's MBTiles WEBP writer encodes VP8 without the alpha
#   band, which turns the transparent (dry / outside-city) part of every tile
#   black. z11..16 from the 1 m source, overviews by averaging.
#
# Requires: GDAL CLI (/opt/homebrew/bin), pmtiles (brew install pmtiles).
# Usage: pipeline/make_scenario_pmtiles.sh <dir> [sid ...]
#   reads  <dir>/chicago_depth_<sid>.tif
#   writes <dir>/depth_<sid>.pmtiles     (skipped if it already exists)
# Default sids: the four bookmarks in pipeline/scenario.py.
set -e
G=/opt/homebrew/bin
DIR=$1; shift
if [ $# -gt 0 ]; then SIDS=("$@"); else SIDS=(r10 b75_2yr b70_100yr b75_100yr); fi
TMP=$(mktemp -d); trap "rm -rf $TMP" EXIT

cat > $TMP/ramp.txt <<RAMP
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

for SID in $SIDS; do
  SRC=$DIR/chicago_depth_$SID.tif
  OUT=$DIR/depth_$SID.pmtiles
  if [ -f $OUT ]; then echo "[$SID] $OUT exists, skipping"; continue; fi
  if [ ! -f $SRC ]; then echo "[$SID] missing $SRC, skipping"; continue; fi
  echo "[$SID] colorize"
  $G/gdaldem color-relief -q $SRC $TMP/ramp.txt $TMP/rgba.tif \
    -alpha -nearest_color_entry -co COMPRESS=DEFLATE -co TILED=YES \
    -co NUM_THREADS=ALL_CPUS -co BIGTIFF=IF_SAFER
  $G/gdalwarp -q -of VRT -t_srs EPSG:3857 -r bilinear $TMP/rgba.tif $TMP/rgba_3857.vrt
  echo "[$SID] mbtiles z16"
  $G/gdal_translate -q -of MBTILES -co TILE_FORMAT=PNG \
    -co ZOOM_LEVEL_STRATEGY=LOWER $TMP/rgba_3857.vrt $TMP/$SID.mbtiles
  echo "[$SID] overviews z11-15"
  $G/gdaladdo -q -r average $TMP/$SID.mbtiles 2 4 8 16 32
  pmtiles convert $TMP/$SID.mbtiles $OUT
  rm -f $TMP/rgba.tif $TMP/$SID.mbtiles
  ls -la $OUT
done
echo "scenario pmtiles -> $DIR"
