#!/bin/zsh
# Sync the PMTiles archives to Cloudflare R2 so a published viewer can read
# them. PMTiles needs HTTP Range + CORS; R2 gives both, and its egress is free,
# which is why the map can be public without a bandwidth bill.
#
# Credentials come from a gitignored .env.publish in the repo root:
#   R2_ACCESS_KEY=...      # token scoped to THIS bucket only
#   R2_SECRET_KEY=...
#   R2_ENDPOINT=https://<account>.r2.cloudflarestorage.com
#   R2_BUCKET=bluespot
#   R2_PUBLIC_BASE=https://<public-host>/     # r2.dev or a custom domain
#
# Usage: pipeline/publish_r2.sh [--dry-run]
set -e
ROOT=${0:a:h}/..
[[ -f $ROOT/.env.publish ]] || { echo "missing .env.publish (see header)"; exit 1 }
set -a; . $ROOT/.env.publish; set +a
SRC=$(cd $ROOT && ./.venv/bin/python -c "import sys;sys.path.insert(0,'pipeline');from paths import data_root;print(data_root())")
DRY=${1:---go}
[[ $DRY == "--dry-run" ]] && FLAG="--dry-run" || FLAG=""

export RCLONE_CONFIG_R2_TYPE=s3 RCLONE_CONFIG_R2_PROVIDER=Cloudflare \
  RCLONE_CONFIG_R2_ACCESS_KEY_ID=$R2_ACCESS_KEY \
  RCLONE_CONFIG_R2_SECRET_ACCESS_KEY=$R2_SECRET_KEY \
  RCLONE_CONFIG_R2_ENDPOINT=$R2_ENDPOINT \
  RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true

for dir in citywide regional; do
  echo "-> $dir"
  # Only the tile archives. COGs stay on Drive: they are the working data, not
  # what the viewer reads, and they are far larger.
  rclone copy "$SRC/$dir" "R2:$R2_BUCKET/$dir" \
    --include "*.pmtiles" \
    --s3-upload-cutoff 100M --s3-chunk-size 64M --transfers 2 \
    --header-upload "Content-Type: application/octet-stream" \
    --header-upload "Cache-Control: public, max-age=604800, immutable" \
    --progress $FLAG
done

echo
echo "published under $R2_PUBLIC_BASE"
echo "set viewer/config.js:  window.BLUESPOT_DATA_BASE = '$R2_PUBLIC_BASE';"
echo "CORS (bucket settings) must allow GET + Range from the site's origin."
