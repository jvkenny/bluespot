#!/bin/zsh
# Build the 7-county CMAP region AOI from the Census TIGER/Line county file.
#
# The CMAP (Chicago Metropolitan Agency for Planning) region is Cook, DuPage,
# Kane, Kendall, Lake, McHenry and Will counties, Illinois (state FIPS 17).
# Per-county identity is kept in the feature properties (NAME, NAMELSAD,
# GEOID, ALAND, AWATER) because the per-county wet-% breakdown is the point
# of the regional product.
#
# NOTE these are the LEGAL county polygons, so Cook and Lake extend miles out
# into Lake Michigan. That is deliberate: no DEM exists over the lake, so
# those cells are simply nodata in the product, and keeping the legal
# boundary means the pools `edge_truncated` test fires on real land edges of
# the region rather than on an arbitrary coastline we drew ourselves.
#
# Source: US Census Bureau TIGER/Line Shapefiles 2024, Counties (and
# equivalent), https://www2.census.gov/geo/tiger/TIGER2024/COUNTY/
# Usage: pipeline/make_region_aoi.sh [workdir]   -> data/aoi/region-cmap7.geojson
set -e
G=/opt/homebrew/bin
REPO=$(cd "$(dirname "$0")/.." && pwd)
WORK=${1:-$(mktemp -d)}
mkdir -p $WORK
ZIP=$WORK/tl_2024_us_county.zip
URL=https://www2.census.gov/geo/tiger/TIGER2024/COUNTY/tl_2024_us_county.zip

if [ ! -f $WORK/tl_2024_us_county.shp ]; then
  [ -f $ZIP ] || curl -fSL -o $ZIP $URL
  unzip -o -q $ZIP -d $WORK
fi

OUT=$REPO/data/aoi/region-cmap7.geojson
rm -f $OUT
$G/ogr2ogr -f GeoJSON $OUT $WORK/tl_2024_us_county.shp \
  -t_srs EPSG:4326 \
  -select STATEFP,COUNTYFP,GEOID,NAME,NAMELSAD,ALAND,AWATER \
  -where "STATEFP='17' AND COUNTYFP IN ('031','043','089','093','097','111','197')"

$G/ogrinfo -q -so -al $OUT | egrep 'Feature Count|Extent'
echo "-> $OUT"
