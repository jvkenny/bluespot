#!/bin/zsh
# Citywide web tiles as PMTiles archives (single-file, HTTP-Range-served —
# an XYZ directory at these zooms would be hundreds of thousands of files).
#
#   depth   : colorized ponding depth, PNG tiles, z11..16 (1 m source; z17
#             would roughly quadruple the archive for sub-pixel gain — the
#             viewer overzooms with nearest resampling instead)
#   terrain : multidirectional hillshade * hypsometric tint, alpha-masked to
#             the city polygon, WEBP tiles, z11..15 (built from a 2 m
#             decimation of the DEM; an underlay does not need 1 m)
#
# Requires: GDAL CLI (/opt/homebrew/bin), pmtiles (brew install pmtiles).
# Usage: pipeline/make_pmtiles.sh <depth_cog.tif> <dem_mosaic.vrt> \
#          <city.geojson> <out_dir>
# Writes <out_dir>/depth.pmtiles and <out_dir>/terrain.pmtiles.
set -e
G=/opt/homebrew/bin
DEPTH=$1; DEMVRT=$2; CITY=$3; OUT=$4
DIR=$(mktemp -d); trap "rm -rf $DIR" EXIT
mkdir -p $OUT

# ---- depth --------------------------------------------------------------
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
echo "[depth] colorize"
$G/gdaldem color-relief -q $DEPTH $DIR/ramp.txt $DIR/rgba.tif \
  -alpha -nearest_color_entry -co COMPRESS=DEFLATE -co TILED=YES
$G/gdalwarp -q -of VRT -t_srs EPSG:3857 -r bilinear $DIR/rgba.tif $DIR/rgba_3857.vrt
echo "[depth] mbtiles z16"
$G/gdal_translate -q -of MBTILES -co TILE_FORMAT=PNG \
  -co ZOOM_LEVEL_STRATEGY=LOWER $DIR/rgba_3857.vrt $DIR/depth.mbtiles
echo "[depth] overviews z11-15"
$G/gdaladdo -q -r average $DIR/depth.mbtiles 2 4 8 16 32
pmtiles convert $DIR/depth.mbtiles $OUT/depth.pmtiles
ls -la $OUT/depth.pmtiles

# ---- terrain ------------------------------------------------------------
echo "[terrain] 2m dem"
$G/gdal_translate -q -outsize 50% 50% -r average $DEMVRT $DIR/dem2m.tif \
  -co COMPRESS=DEFLATE -co TILED=YES
echo "[terrain] hillshade + tint"
$G/gdaldem hillshade -q -multidirectional -compute_edges $DIR/dem2m.tif $DIR/hs.tif \
  -co COMPRESS=DEFLATE -co TILED=YES
cat > $DIR/tint.txt <<RAMP
nv 0 0 0
172 138 152 134
177 172 181 155
180 208 204 176
183 224 213 185
186 222 202 168
190 210 186 150
195 193 168 133
RAMP
$G/gdaldem color-relief -q $DIR/dem2m.tif $DIR/tint.txt $DIR/tint.tif \
  -co COMPRESS=DEFLATE -co TILED=YES
echo "[terrain] blend + city-mask alpha (windowed)"
PY="$(cd "$(dirname "$0")/.." && pwd)/.venv/bin/python"
$PY - $DIR $CITY <<'PY'
import json, sys, numpy as np, rasterio
from rasterio.features import rasterize
from rasterio.warp import transform_geom
d, city_path = sys.argv[1], sys.argv[2]
hs = rasterio.open(f"{d}/hs.tif"); tint = rasterio.open(f"{d}/tint.tif")
city = [transform_geom("EPSG:4326", tint.crs, f["geometry"])
        for f in json.load(open(city_path))["features"]]
prof = tint.profile
prof.update(count=4, compress="deflate", tiled=True)
with rasterio.open(f"{d}/blend.tif", "w", **prof) as out:
    for _, win in tint.block_windows(1):
        h = hs.read(1, window=win).astype("float32") / 255.0
        t = tint.read(window=win).astype("float32")
        b = np.clip(t * (0.30 + 0.70 * h), 0, 255).astype("uint8")
        out.write(b, window=win, indexes=[1, 2, 3])
        a = rasterize(city, out_shape=(int(win.height), int(win.width)),
                      transform=tint.window_transform(win), fill=0,
                      default_value=255, dtype="uint8")
        out.write(a, window=win, indexes=4)
PY
$G/gdalwarp -q -of VRT -t_srs EPSG:3857 -r bilinear $DIR/blend.tif $DIR/blend_3857.vrt
echo "[terrain] mbtiles z15"
$G/gdal_translate -q -of MBTILES -co TILE_FORMAT=WEBP \
  -co ZOOM_LEVEL_STRATEGY=LOWER $DIR/blend_3857.vrt $DIR/terrain.mbtiles
$G/gdaladdo -q -r average $DIR/terrain.mbtiles 2 4 8 16
pmtiles convert $DIR/terrain.mbtiles $OUT/terrain.pmtiles
ls -la $OUT/terrain.pmtiles
echo "pmtiles -> $OUT"
