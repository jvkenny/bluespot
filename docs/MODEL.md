# Toward a real scenario model (design note, 2026-08-17)

Static depression fill answers "where CAN water sit" — the upper envelope.
The next model answers "which pools activate under HOW MUCH rain," which ties
the map to the design-storm story (ISWS Bulletin 70 → 75, NOAA Atlas 15).

## Fill–spill scenario model (v0.2 target)
For each depression from the fill step:
1. **Stage–storage curve** — from the depth raster itself: volume as a
   function of water level, per pool. (Cheap: sort cell depths.)
2. **Catchment** — D8 flow directions on the *filled* DEM route every cell to
   the pool (or river/edge) it drains to. Candidate libs: pysheds or richdem;
   both beat hand-rolled numpy for 10^8-cell domains.
3. **Loading** — rain depth R × catchment area × runoff coefficient
   (impervious fraction from NLCD) − a uniform drainage-capacity term
   (mm/hr the sewers plausibly remove; stated as an assumption slider, since
   the real network is not public data).
4. **Spill cascade** — pools that overtop pass excess to their downstream
   neighbor (Barnes' Fill-Spill-Merge is the reference algorithm).

## UI
A single "how much rain?" control with bookmarks at: 1963 design storm
(Bulletin 70), today's 100-yr (Bulletin 75), mid-century (Atlas 15, when
published). The map shows pools appearing/deepening as the slider moves —
the design-storm gap made visible per block.

Honesty carryover: still not hydraulics; the drainage-capacity term is an
explicit assumption, displayed, adjustable.

## Implementation notes (v0.2, implemented 2026-08-17, pipeline/scenario.py)

Pragmatic choices vs. the design above, in the order of the model steps:

1. **Stage–storage**: exact, from sorted raw-DEM cell elevations per pool.
   Pools = 8-connected components of (filled − raw) ≥ 5 cm on the buffered
   compute domain (same fill as bluespot.py). Given a stored volume, the
   water surface is solved analytically, so cells submerge bottom-up.
2. **Catchments**: hand-rolled vectorized numpy D8 on the filled DEM rather
   than pysheds/richdem (both are compiled/numba deps that don't yet track
   Python 3.14; the pilot domain is ~10⁷ cells, well within numpy range).
   Terminals are pool cells, open-water cells, and the domain border. Flats
   (guaranteed drainable on a filled surface outside pools) resolve by
   iteratively adopting an equal-elevation draining neighbor; catchment
   assignment by pointer doubling. Every valid cell ends at a pool, water,
   or the edge.
3. **Loading**: net depth = max(0, C·R − D) with uniform runoff coefficient
   **C = 0.55** (dense urban residential mix) and drainage-capacity
   assumption **D = 10 mm** of runoff removed per event (sewer/inlet capture
   — the real network is not public data). Both are constants at the top of
   scenario.py; NLCD imperviousness refinement remains a stretch goal.
   *(Superseded 2026-08-19: C is gone, replaced by a per-cell curve number.
   See "v0.4 — spatially varying runoff" at the end of this file. D is
   unchanged and is now the only uniform term.)*
4. **Spill cascade**: simplified Fill-Spill-Merge. Each pool's downstream is
   whatever its lowest adjacent outside cell drains to (excluding cells that
   drain straight back in). Pools process in topological order; overflow
   passes downstream until it stores or exits at water/edge. Mutual-spill
   cycles (equal saddles) are filled members-by-pour-elevation and residual
   excess is counted as exported — a conservative simplification.
5. **Output**: one AOI-cropped float32 depth GeoTIFF per rainfall bookmark,
   same conventions as the static layer, tiled by make_tiles.sh into
   viewer/tiles/depth_<id>. Bookmarks (verified, data/SOURCES.md #4):
   1.0 in reference nuisance rain; 3.34 in (Bulletin 75 2-yr 24-hr NE IL);
   7.58 in (Bulletin 70 100-yr 24-hr, superseded); 8.57 in (Bulletin 75
   100-yr 24-hr, current); plus the static full fill as the max envelope.

Known limits, beyond the static layer's: catchments truncate at the 1 km
compute buffer, so pools near the AOI edge under-collect; uniform C and D
ignore land cover and the real sewer network entirely; the cascade has no
timing (an event is a single bucket of water); NOAA Atlas 15 mid-century
bookmark waits on publication.

## Citywide (v0.3, 2026-08-18, `scenario.py --chunked`)

The pilot ran the whole AOI as one domain. The city does not fit: a
single-domain solve of Chicago would be ~2×10⁹ cells. So the citywide run
mirrors `bluespot.py`'s chunking exactly — **one chunk per USGS 10 km DEM
tile, core plus a 1 km halo** read from a VRT mosaic pinned to the 18
IL_4_County_QL1_LiDAR_2016 tiles that meet the city (`select_tiles`; the
Drive DEM folder is shared and also holds other projects and wider-area
tiles, so the mosaic is selected by project + AOI, never by a bare glob).
Each chunk runs in **its own subprocess** — the arrays are large enough that
allocator retention across chunks, not any single chunk, is what pushes RSS
up. Peak RSS is ~6.6 GB per chunk (12k × 12k domain) and returns to zero
between chunks.

### What chunking costs, and why the halo is 1 km
Fill, D8 routing, catchment accumulation and the spill cascade are **all
solved per chunk**, so all three truncate at the halo:

- a pool whose contributing area reaches more than 1 km past its tile core
  **under-collects** — the missing upslope cells simply never load it;
- a spill cascade that would continue past the halo is cut short, and the
  residual is counted as exported rather than stored downstream.

Both push the same way: **chunking biases stored volume LOW**, and the bias
concentrates near chunk seams and on features with long contributing areas
(rail trenches, the Des Plaines and Calumet valleys, expressway corridors).

The halo width was chosen by measurement, not assertion. The downtown tile
(x44y464 — the Eisenhower trench, the biggest pool in the city) was solved
twice, at 1 km and 2 km halo, and the **identical** 10 km core compared:

| bookmark | core stored, 1 km halo | 2 km halo | change |
|---|---|---|---|
| 1.0″ | 228,238 m³ | 229,359 m³ | +0.49% |
| 3.34″ | 1,674,258 m³ | 1,697,670 m³ | +1.38% |
| 7.58″ | 3,268,916 m³ | 3,329,694 m³ | +1.83% |
| 8.57″ | 3,556,986 m³ | 3,626,620 m³ | +1.92% |
| static full fill | 11,528,063 m³ | 11,954,305 m³ | +3.57% |

Doubling the halo — 1.5× the runtime, 8.5 GB peak — moves the rain
scenarios by under 2%. Two things are worth saying about that table:

1. The rain scenarios are **less** halo-sensitive than the static fill
   (≤1.92% vs 3.57%). That is the expected direction: outside the largest
   basins these scenarios are *load*-limited, not *capacity*-limited, so
   giving a seam-adjacent pool more capacity changes nothing unless there is
   also more water to put in it.
2. 1 km keeps the scenario layers on **exactly the same fill domains, and
   therefore the same pool geometry, as the shipped static depth COG**,
   which was built by `bluespot.py` at a 1 km halo. That makes "every rain
   stop is a subset of the max layer" true cell-by-cell rather than merely
   on average — the invariant the viewer's rain control is built on.

So: 1 km, with the ~0.5–2% low bias on stored volume stated rather than
hidden. A single-domain citywide solve remains the only way to remove it.

### Mass balance
Every chunk checks, per bookmark, that `loaded = stored + exported` over its
whole domain (halo included) — loaded being net rain depth × catchment area
summed over pools. Observed relative imbalance is at float round-off,
|ε| < 1e-14, against a 0.1% bug threshold. Citywide wet% and stored volume,
by contrast, are accumulated from the **cropped, city-masked cores only**, so
neither halo overlap nor cross-chunk double counting can inflate them.
