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
- `data/raw/` and `data/derived/` are gitignored: raw inputs must be
  re-fetchable by script from public sources; large derived artifacts are
  backed up to the maintainer's Google Drive (folder: bluespot-data).
- Private repo until the maintainer explicitly says to publish. Never enable
  GitHub Pages or make the repo public without being asked.

Conventions:
- Pipeline scripts are stdlib + numpy/rasterio/scikit-image (repo .venv);
  GDAL CLI for format conversion; deterministic, re-runnable, idempotent.
- Viewer is plain MapLibre GL JS, no framework, static-hostable.
- CRS: compute in EPSG:26916 (UTM 16N) or the DEM's native CRS; serve web
  tiles in EPSG:3857. AOIs defined in EPSG:4326 GeoJSON in data/aoi/.
