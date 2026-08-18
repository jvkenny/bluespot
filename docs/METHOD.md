# Method — bluespot depth layer (v1 citywide, v2 regional)

Sections 1-5 describe the method. The **Regional extension**
section near the end covers what changes at 7-county scale; the
method itself does not change, only the machinery around it.

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

## Regional extension (v2 — the 7-county CMAP region)

Coverage grows from the City of Chicago (606 km2, 18 DEM tiles) to Cook,
DuPage, Kane, Kendall, Lake, McHenry and Will counties: 10,348 km2 of land,
124 DEM tiles, 27 GB of raw elevation. The fill method is unchanged. Four
things about the region are worth stating plainly.

### Multiple lidar vintages, and where the seams are
The city sat inside a single 2016 acquisition. The region does not. Across
the 7 counties TNM offers 1-3 overlapping projects for most 10 km cells, so
`pipeline/fetch_dem_region.py` picks exactly ONE project per cell from a
priority list rather than taking whatever sorts first. That makes vintage
seams follow acquisition boundaries deliberately instead of checkerboarding
cell by cell. The chosen mix:

| project | cells | published |
|---|---|---|
| IL_4_County_QL1_LiDAR_2016_B16 | 105 | 2024-11-18 |
| IL_10CountyNRCS_D23 | 8 | 2026-04-04 |
| IL LaSalle B2 2017 | 6 | 2020-03-30 |
| IL_MidNorth_D22 | 3 | 2023-10-31 |
| IL LaSalle B1 2017 | 2 | 2020-03-30 |

IL_4_County_QL1 ranks first for two reasons: it alone covers 85% of the
region as one consistent acquisition, and it is the acquisition the citywide
product was built from, so pinning it keeps the regional product identical
to the citywide one over Chicago (verified — see the consistency check in the
repo report). The remaining 19 cells form a fringe on the western and
southern edges.

**Cross-vintage seams are a real caveat.** Where a 2016 cell abuts a 2023 or
2017 cell, the two sides were flown years apart with different sensors and
processing. Ground that was regraded in between — new subdivisions, detention
basins, highway work — changes across the seam, and a depression straddling
one is filled from two slightly different surfaces. Depths near those
boundaries should be read as approximate. Every tile's project and
publication date is recorded in `<data_root>/dem/MANIFEST.jsonl`, and the
full selection (including the alternatives rejected per cell) in
`<data_root>/regional/dem_plan.json`, so any seam can be traced to its two
acquisitions.

### A real hole in coverage: western Will County
West and southwest Will County — roughly 636 km2, about 29% of the county's
land — has **no published 3DEP 1 m DEM at all**. This is not a selection
artifact: TNM returns zero 1 m DEM products for that area. Lidar was flown
(IL_19County_D24, point cloud published 2026-04-28) but no raster derivative
has been released, and deriving a DEM from raw point clouds is out of scope
here. Consequence: Will County's numbers describe only the ~71% of it the
product can see, and the regional map has a visible blank there. The
per-county table reports covered area next to legal land area for exactly
this reason — a wet-% over an unstated denominator is a misleading number.

### Chunking at 124 tiles: one process per chunk
The citywide run did every chunk inside one python process and its RSS crept
from ~4 GB to 9.2 GB, because freed numpy blocks are retained by the
allocator and `skimage.morphology.reconstruction` leaves large transients.
That is survivable over 18 chunks and not over 124. `pipeline/bluespot_region.py`
runs each chunk in its own subprocess, so every byte returns to the OS at
chunk exit and peak memory is one chunk's worth regardless of chunk count —
measured 2-5 GB per worker, 3 workers concurrently. Two other scale changes:
water polygons are bbox-filtered to the chunk before rasterizing (the
regional OSM water file holds 22,009 polygons; rasterizing all of them into
each of 124 windows is pure waste), and per-chunk stats are written to
`chunkstats/` so an interrupted run resumes without recomputing.

The 1 km halo and its trade-off are unchanged from the citywide method
(above) — but note the region contains genuinely long depressions (the Des
Plaines and Fox valleys, the I&M canal corridor) where the halo assumption
bites harder than it does inside the city.

### Denominators, and the lake
The AOI is the **legal** TIGER county polygons, so Cook and Lake extend
miles out into Lake Michigan. No DEM exists there, so those cells are nodata
and drop out of every statistic. Reported "land cells" therefore means
"land this product can actually see", which is what the per-county table's
covered-km2 column makes explicit. Keeping the legal boundary (rather than
drawing our own coastline) also means the pools `edge_truncated` test fires
on real land edges of the region.

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
sub-pixel gain), terrain PNG z11–15 from a 2 m decimation, alpha-masked to
the city (PNG, not WEBP: GDAL's MBTiles WEBP writer drops the alpha
band, blacking out the outside-city part of edge tiles). Archives live on Drive (`bluespot-data/citywide/`), reached from
the repo via the gitignored `viewer/data` symlink. PMTiles requires HTTP
Range requests, which `python -m http.server` does not honor — use
`pipeline/serve.py` (stdlib, Range-capable).
