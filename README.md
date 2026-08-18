# Bluespot

**A community-first climate atlas. Chicago's North Side first, then outward.**

Where does the land want to hold water when the rain comes harder than the pipes
were built for? Where does missing tree canopy leave a block hotter than the one
beside it? Bluespot answers those questions from open data only, with every
number traceable to a cited public source — built for residents, not agencies.

## What this is (and isn't)

- **Is:** terrain screening. The bluespot method fills every depression in a
  1-meter lidar elevation model and differences it against the raw terrain —
  the residual is where water pools, and how deep, when intensity exceeds
  drainage. Plus canopy/heat exposure, and how both are changing.
- **Is not:** a flood model. It knows nothing of storm sewers, culverts, or
  soil. It shows what the ground does, not what the drainage system saves.
  Every page says so.

## Principles

1. **Open data, open method, open source.** Anyone can rebuild every artifact.
2. **Places, not assets.** This project describes the hazard exposure of
   places for the people who live there. It is not asset management software
   and never touches agency asset registries.
3. **Cited or absent.** Every plotted number derives from a public source
   listed in `data/SOURCES.md`.
4. **Cloud-native static.** COGs + tiles + MapLibre. No server, nothing to
   subscribe to, forkable forever.

## Layout

- `pipeline/` — fetch + analysis (Python/GDAL/QGIS-grade raster work)
- `data/` — AOI definitions and source manifest. Heavy data (raw DEMs,
  region-scale outputs) lives primarily on Google Drive (`bluespot-data/`,
  see `pipeline/paths.py`); local `data/raw/` is only a transient cache
- `viewer/` — MapLibre globe → neighborhood scrollytelling front end
- `docs/` — method notes

## Running the viewer

The depth and terrain layers are PMTiles archives on Google Drive, reached
through the gitignored `viewer/data` symlink. The symlink points at the
**root** of the data folder, and the viewer addresses products by
sub-directory — `data/citywide/depth.pmtiles`, `data/regional/depth.pmtiles`
— so one link serves every extent:

    ln -s "$HOME/Library/CloudStorage/GoogleDrive-<account>/My Drive/bluespot-data" viewer/data

    bluespot-data/
      dem/              raw USGS 1 m tiles + MANIFEST.jsonl  (shared)
      north-side-pilot/ pilot depth raster + water
      citywide/         City of Chicago COG + PMTiles + water
      regional/         7-county COG + PMTiles + water + dem_plan.json

(If you have the older link pointing straight at `citywide/`, replace it —
the viewer now expects the root.)

PMTiles needs HTTP Range requests and `python -m http.server` does not
support them. Serve the viewer with the stdlib Range-capable server instead:

    python3 pipeline/serve.py            # http://localhost:8666/

Rebuild artifacts, city scale: `pipeline/fetch_dem.py` →
`pipeline/fetch_water.py` → `pipeline/bluespot.py --chunked` →
`pipeline/pools.py` → `pipeline/make_pmtiles.sh`; rain scenarios:
`pipeline/scenario.py --chunked` → `pipeline/make_scenario_pmtiles.sh`
(docs/MODEL.md); region scale: same fill pipeline over
`data/aoi/region-cmap7.geojson` (docs/METHOD.md).

Rebuild artifacts, region scale: `pipeline/make_region_aoi.sh` →
`pipeline/fetch_dem_region.py` → `pipeline/fetch_water_region.py` →
`pipeline/bluespot_region.py` → `pipeline/pools.py` +
`pipeline/county_stats.py` → `pipeline/make_pmtiles.sh` (with `DECIM_PCT=25`).
See docs/METHOD.md, including the regional section on lidar vintages and the
gap in western Will County.

Status: internal development. Coverage: the 7-county CMAP region — Cook,
DuPage, Kane, Kendall, Lake, McHenry and Will counties, Illinois — with the
City of Chicago and the North Side pilot as nested products.

Regional product at a glance: 8,438 km2 of visible land out of 10,348 km2
legal land area, 12.09% of it wet at 5 cm or more, 770 million m3 of
capacity. Every county is at least 99% covered except Will, which has only
15% — a real hole in published 3DEP 1 m DEM coverage, not a processing
choice. Read docs/METHOD.md before quoting any of these numbers; the Will
caveat and the fact that the deepest "pools" are working quarries both
matter.
