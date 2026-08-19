#!/bin/zsh
# Pool outlines come off the raster as per-cell staircases — faithful but far
# too heavy for a phone (region_pools was 7.9 MB, which stalled first paint on
# mobile). Simplify at 4 m in a metric CRS: invisible at display zooms, ~4x
# lighter. Display geometry only; all attributes (area, volume, depth) are
# carried through untouched and still come from the full-resolution raster.
# Usage: pipeline/simplify_pools.sh viewer/region_pools.geojson [tolerance_m]
set -e
SRC=$1; TOL=${2:-4}
T=$(mktemp -d)
ogr2ogr -f GeoJSON $T/m.json "$SRC" -t_srs EPSG:3857
ogr2ogr -f GeoJSON $T/s.json $T/m.json -simplify $TOL
ogr2ogr -f GeoJSON $T/o.json $T/s.json -t_srs EPSG:4326 -lco COORDINATE_PRECISION=6
mv $T/o.json "$SRC"; rm -rf $T
echo "simplified $SRC at ${TOL}m -> $(du -h "$SRC" | cut -f1)"
