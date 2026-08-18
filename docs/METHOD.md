# Method — bluespot depth layer (v1, citywide)

1. **DEM**: USGS 3DEP 1m bare-earth DEM (`pipeline/fetch_dem.py`, TNM API,
   provenance in `<data_root>/dem/MANIFEST.jsonl` on Drive). Citywide: 18
   10 km tiles, all from the single 2016 IL_4_County_QL1 acquisition
   (overlapping newer projects excluded to avoid cross-vintage seams).
2. **Compute domain**: per-DEM-tile chunks. Each 10 km tile core plus a
   1 km halo read from a VRT mosaic of all tiles, so every core cell has at
   least 1 km of real terrain context in every direction. Chunking bounds
   peak memory (~12k×12k float32, ≈3–4 GB) regardless of city size.
3. **Outlets**: the chunk-domain edge, plus all open-water cells (OSM
   `natural=water` polygons, `pipeline/fetch_water.py`). Water-as-outlet is
   required because 3DEP DEMs retain bridge decks, which otherwise dam the
   river channel and back-fill the whole basin (observed: 66% of pilot land
   "wet" without it; 13.7% with it).
   - **Lake Michigan** arrives from Overpass as multipolygon relation
     1205149 whose outer ring is ~750 separate way segments;
     `fetch_water.py` stitches member ways end-to-end into closed rings and
     assigns inner rings as holes (so islands — Goose Island — stay land).
     With the lake as an outlet the East Side drains correctly instead of
     back-filling from the shoreline.
4. **Fill**: morphological reconstruction by erosion (Vincent 1993) — exact
   depression filling, no min-slope. `skimage.morphology.reconstruction`.
5. **Depth** = filled − raw, values < 5 cm zeroed, open water masked to
   nodata, halo cropped off, masked to the **city boundary polygon**
   (Chicago Data Portal), and chunk rasters mosaicked to a single citywide
   COG (`gdalbuildvrt` + `gdal_translate -of COG`, on Drive).

## Chunking trade-off (say this too)
A depression that extends more than 1 km beyond a tile edge sees an
artificial outlet at the halo boundary, so depths in multi-kilometre
features (long rail trenches, the Des Plaines valley) can be slightly
underestimated near chunk seams, and the two sides of a seam are filled in
separate domains. Clipped to the pilot AOI, the citywide result matches the
pilot single-domain fill closely (see repo report); differences are the
halo-geometry change, not the method.

Two pilot-vs-citywide deltas are understood and expected:
- The pilot's Kennedy-trench pool (its #1, edge-truncated at the pilot AOI
  edge, max 3.48 m) fills to 6.86 m citywide — the pilot's domain edge was
  acting as an artificial outlet inside the pool.
- v0's Overpass parser force-closed relation member segments with straight
  chords, which falsely masked ~25% of the pilot window as "water" (5.8M
  cells vs 0.26M with correct assembly). v1's ring stitching fixes this;
  pilot wet% is unchanged (13.74 → 13.75) because the false mask was
  scattered rather than concentrated in wet areas.

## Known limits (say these out loud in any UI)
- Terrain screening, not hydraulics: no sewers, culverts, infiltration, or
  rainfall volume — it is the *upper envelope* of where water can gather.
- Bare-earth DEM: buildings are removed; pools "inside" building footprints
  are meaningless at parcel scale.
- OSM water coverage gates outlet quality; validate per-AOI.
- 2016 lidar: post-2016 regrading/construction is invisible (e.g. the
  O'Hare terminal-area works).
- The product is clipped to the city limits; ponding physically continues
  into the suburbs and pools crossing the line carry an `edge_truncated`
  flag (in-city fragment only).

## Validation TODO
- Ground-truth against Aug 2026 rain event (maintainer's own observations,
  311 water-in-street complaints, MWRD overflow records).
- Riverside pools at the Horner Park reach need a look — possible OSM water
  polygon vs. DEM channel misalignment.

## Pools layer (pipeline/pools.py)
Connected regions ≥ 15 cm deep and ≥ 400 m², ranked by stored volume; names
reverse-geocoded from OSM Nominatim (working labels, hand-curate before any
public use). Citywide the raster (~2G cells) no longer fits in RAM for
labeling, so components are found on a decimated (4 m) read and each
candidate is then re-read at full 1 m resolution in its own window for
exact area / volume / max depth / outline; 2× the requested top-N
candidates are refined so coarse-rank swaps near the cutoff don't drop a
real top-N pool. Pools touching the city boundary get
`edge_truncated: true` — their figures are fragments of a feature that
continues outside the product.

## Web delivery (pipeline/make_pmtiles.sh, pipeline/serve.py)
Depth and terrain ship as PMTiles archives (GDAL MBTiles + `pmtiles
convert`): depth PNG z11–16 (1 m source; z17 would ~4× the archive for
sub-pixel gain), terrain WEBP z11–15 from a 2 m decimation, alpha-masked to
the city. Archives live on Drive (`bluespot-data/citywide/`), reached from
the repo via the gitignored `viewer/data` symlink. PMTiles requires HTTP
Range requests, which `python -m http.server` does not honor — use
`pipeline/serve.py` (stdlib, Range-capable).
