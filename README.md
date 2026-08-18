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

The depth and terrain layers are PMTiles archives on Google Drive
(`bluespot-data/citywide/`), reached through the gitignored `viewer/data`
symlink:

    ln -s "$HOME/Library/CloudStorage/GoogleDrive-jkenny2334@gmail.com/My Drive/bluespot-data/citywide" viewer/data

PMTiles needs HTTP Range requests and `python -m http.server` does not
support them. Serve the viewer with the stdlib Range-capable server instead:

    python3 pipeline/serve.py            # http://localhost:8666/

Rebuild artifacts: `pipeline/fetch_dem.py` → `pipeline/fetch_water.py` →
`pipeline/bluespot.py --chunked` → `pipeline/pools.py` →
`pipeline/make_pmtiles.sh` (see docs/METHOD.md).

Status: internal development. Coverage: the full City of Chicago (pilot was
North Center / Roscoe Village / Lincoln Square).
