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
