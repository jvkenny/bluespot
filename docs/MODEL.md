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
