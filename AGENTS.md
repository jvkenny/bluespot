# Bluespot — agent instructions

Read the repo README first; its Principles section is the constitution.

Hard rules:
- **Public data only.** No agency asset registries, no EAM/Cartegraph/OpenGov
  concepts, vocabulary, or data. This project is deliberately unrelated to the
  maintainer's employer and must not describe infrastructure asset management.
- **Honesty guardrails.** Bluespot output is terrain screening, not flood
  prediction — any UI or prose presenting it must say so. No dollar-cost
  claims. Every dataset gets an entry in data/SOURCES.md with URL + retrieval
  date before it is used.
- **Large data lives on Google Drive, not local disk** (folder
  `bluespot-data/`, resolved by `pipeline/paths.py`; override with
  $BLUESPOT_DATA_ROOT). Raw DEMs download to `<data_root>/dem/` on Drive.
  Local `data/raw/` is a transient cache only — safe to delete, never the
  primary copy. `data/derived/` holds small AOI-scale outputs; region-scale
  derived artifacts also go to Drive. Everything must stay re-fetchable or
  re-computable by script from public sources.
- **PUBLIC as of 2026-08-19** (John's explicit go-ahead). Code MIT, derived
  data ODbL — see LICENSE and LICENSE-DATA.md; keep attribution intact in the
  viewer. Tiles are served from Cloudflare R2, not the repo. Treat anything
  added here as world-readable.

Conventions:
- Pipeline scripts are stdlib + numpy/rasterio/scikit-image (repo .venv);
  GDAL CLI for format conversion; deterministic, re-runnable, idempotent.
- Viewer is plain MapLibre GL JS, no framework, static-hostable.
- CRS: compute in EPSG:26916 (UTM 16N) or the DEM's native CRS; serve web
  tiles in EPSG:3857. AOIs defined in EPSG:4326 GeoJSON in data/aoi/.
