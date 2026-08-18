# Method — bluespot depth layer (v0)

1. **DEM**: USGS 3DEP 1m bare-earth DEM (`pipeline/fetch_dem.py`, TNM API,
   provenance in `data/raw/MANIFEST.jsonl`).
2. **Compute domain**: AOI bounds + 1 km buffer, so clip-edge artifacts fall
   outside the product.
3. **Outlets**: the domain edge, plus all open-water cells (OSM
   `natural=water` polygons, `pipeline/fetch_water.py`). Water-as-outlet is
   required because 3DEP DEMs retain bridge decks, which otherwise dam the
   river channel and back-fill the whole basin (observed: 66% of land "wet"
   without it; 13.7% with it).
4. **Fill**: morphological reconstruction by erosion (Vincent 1993) — exact
   depression filling, no min-slope. `skimage.morphology.reconstruction`.
5. **Depth** = filled − raw, values < 5 cm zeroed, open water masked to
   nodata, cropped to AOI. Cells ≥ 5 cm ≈ 13.7% of pilot land; deepest pools
   are rail/expressway viaducts (max 3.48 m in pilot).

## Known limits (say these out loud in any UI)
- Terrain screening, not hydraulics: no sewers, culverts, infiltration, or
  rainfall volume — it is the *upper envelope* of where water can gather.
- Bare-earth DEM: buildings are removed; pools "inside" building footprints
  are meaningless at parcel scale.
- OSM water coverage gates outlet quality; validate per-AOI.
- 2016 lidar: post-2016 regrading/construction is invisible.

## Validation TODO
- Ground-truth against Aug 2026 rain event (maintainer's own observations,
  311 water-in-street complaints, MWRD overflow records).
- Riverside pools at AOI west edge (Horner Park reach) need a look — possible
  OSM water polygon vs. DEM channel misalignment.

## Pools layer (pipeline/pools.py)
Connected regions ≥ 15 cm deep and ≥ 400 m², ranked by stored volume; names
reverse-geocoded from OSM Nominatim (working labels, hand-curate before any
public use). Known issue: pools touching the AOI boundary (e.g. #1, the
Kennedy mainline trench) are edge-truncated — their area/volume are fragments
of the real feature. Flag or merge these when the AOI grows.
