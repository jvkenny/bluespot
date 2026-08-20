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

## v0.4 — spatially varying runoff (2026-08-19, `pipeline/cn.py`)

v0.2 and v0.3 turned rain into runoff with a single number: **C = 0.55**,
"dense urban residential mix", applied to every square metre from the Loop to
Beverly to the O'Hare grasslands. It was a placeholder, and the roadmap's
Phase 1 says the depths have to be defensible before anything gets built on
top of them. v0.4 replaces it with the NRCS **curve number** method — seventy
years old, published as a federal directive, and what an actual drainage
study would use.

### What the model now does per cell

    S   = 1000/CN - 10                        potential retention, inches
    Ia  = 0.2 S                               initial abstraction
    Q   = (P - Ia)^2 / (P + 0.8 S)   P > Ia   runoff, inches
    net = max(0, 25.4 Q - D)                  runoff reaching the pool, mm

`Q` is where land cover and soil enter. `D` is the same 10 mm of sewer and
inlet capture as before, taken off each cell's runoff rather than off a
pool's total, and it is now the **only uniform term left in the model**.
Runoff accumulates per pool through the D8 catchment assignment that was
already there, so the fill, the pool geometry, the stage–storage solve and
the spill cascade are all untouched. That is worth stating precisely, because
it is also the regression test: the static full-fill layer comes out
**bit-identical** to v0.3, citywide and per chunk.

Two properties of the curve number do most of the work in the results below.
It is **nonlinear in rain depth** — a small storm produces far less runoff
than `C·R` implies and a large one considerably more — and it has a
**threshold**: nothing runs off until the initial abstraction is satisfied.

### The curve-number grid

`pipeline/cn.py` builds it in two stages. Stage 1 works at 30 m in EPSG:5070
on the NLCD grid itself, so the two NLCD rasters need no resampling at all.
Stage 2 writes **one CN raster per DEM tile, with that tile's CRS, transform
and shape copied verbatim**, so a scenario chunk reads the same window from
the CN mosaic that it reads from the DEM mosaic and the arrays line up by
index; `cn_read_window` asserts the grids agree rather than trusting them to.
The whole citywide CN tile set is 36 MB.

Inputs, all public domain, all cited in data/SOURCES.md (#9–#12):

- **NLCD 2021 Land Cover** and **NLCD 2021 Percent Developed Imperviousness**
  (MRLC/USGS, 30 m), fetched as AOI subsets through the MRLC WCS rather than
  as ~2 GB CONUS downloads — the city subset takes two seconds.
- **SSURGO hydrologic soil group** (USDA-NRCS). Note this is SSURGO through
  Soil Data Access — map-unit polygons from the SDA WFS and
  `component.hydgrp` from the SDA tabular REST endpoint — not the gridded
  gSSURGO raster product. Same survey data, scriptable delivery, no
  2–4 GB state geodatabase to download by hand.

The pervious curve number comes from this table, which is TR-55 Tables 2-2a
and 2-2c (equally, NEH Part 630 Subpart E). **NRCS publishes no NLCD
crosswalk**, so the middle column — which TR-55 cover description each NLCD
class borrows — is ours, and is the part to argue with:

| NLCD | class | TR-55 cover borrowed | A | B | C | D |
|---|---|---|---|---|---|---|
| 11 | Open Water | our rule: CN 98 | 98 | 98 | 98 | 98 |
| 12 | Perennial Ice/Snow | our rule: CN 98 | 98 | 98 | 98 | 98 |
| 21–24 | Developed (all four) | urban open space, good condition | 39 | 61 | 74 | 80 |
| 31 | Barren Land | newly graded, pervious only | 77 | 86 | 91 | 94 |
| 41–43 | Forest (dec./ever./mixed) | woods, good condition | 30 | 55 | 70 | 77 |
| 51–52 | Scrub | brush–weed–grass, fair condition | 35 | 56 | 70 | 77 |
| 71–74, 81 | Grass, sedge, pasture/hay | pasture/grassland/range, good | 39 | 61 | 74 | 80 |
| 82 | Cultivated Crops | row crops, straight row, good | 67 | 78 | 85 | 89 |
| 90, 95 | Wetlands | our rule: CN 98 | 98 | 98 | 98 | 98 |

That pervious CN is then composited with the measured impervious fraction by
NRCS's own equation (NEH eq. 9-1 / Subpart E eq. 630E-1):

    CN = CN_pervious + f_impervious * (98 - CN_pervious)

**All four Developed classes share one pervious CN on purpose.** NRCS's
composite equation assumes the pervious part of urban land is "equivalent to
pasture in good hydrologic condition" — which is why the open-space-good and
pasture-good rows above carry identical numbers — and the NLCD Developed
classes are *defined* by imperviousness bins. Using both the class and the
measured percentage would count the same pavement twice. All the urban
variation comes from the imperviousness raster, where it is measured.

Result over Chicago: mean CN **91.5**, median 92, 5th–95th percentile 83–98;
64.1% of city land HSG C and 35.0% D after the dual rule, 0.9% A, 0.05% B;
mean imperviousness **68%**. Per chunk the mean CN runs 87.3 (the far
northwest, O'Hare's grasslands and forest preserve) to 93.8 (downtown).

### Data-quality surprises, and the rules used

**Soil groups run out under a city, as expected.** SSURGO map units like
"Urban land", "Made land", "Pits" and "Water" are miscellaneous areas, not
soils, and NRCS assigns them no hydrologic group at all — 16 of the 431 map
units in the Chicago fetch have a NULL `hydgrp` for every component. Over the
city that leaves **0.78% of land** with nothing. **Fill rule: those cells
take the group of the nearest cell that has one** (Euclidean, on the 30 m
grid). The median borrow distance is **30 m — one cell** — and the maximum is
752 m, so this is filling pinholes, not painting over a hole. Borrowing the
neighbour is the right shape of answer: the till under the pavement is the
same till as next door, and the pavement itself is already counted by the
imperviousness raster. The fraction and the distance distribution are
recorded in `<data_root>/cn/cn30_chicago.json` and echoed into the published
scenario JSON.

**Dual soil groups are the assumption that matters, and it matters far more
outside the city.** SSURGO reports A/D, B/D, C/D where the group depends on
whether the soil has been artificially drained: first letter drained, second
undrained. We assume **undrained, so all three become D** — the standard,
conservative reading, and what the soil is unless somebody drained it. Inside
Chicago that touches **3.6%** of the land and barely moves anything. Over the
7-county region the same script reports **39.9%**, and NE Illinois farmland
is extensively tile-drained, so **the regional grid will systematically
overstate runoff on cropland**. That has to be said before the regional
ladder runs; a public drainage layer would fix it, and there may not be one.

**Wetlands are our call, not NRCS's.** TR-55 has no wetland row. We give NLCD
90/95 CN 98 for every soil group on the grounds that saturated ground has no
available retention. It is the most conservative reading, and it is small:
wetlands are 1.3% of Chicago's land, and most of that sits inside depressions
that are already pools in this model.

**Connected impervious.** NRCS's CN 98 assumes impervious surface drains
directly to the storm system. A roof draining onto a lawn does not. TR-55
offers an unconnected variant for watersheds under 30% impervious; Chicago
averages 68%, so the connected assumption is right here and would be wrong at
the leafy end of the region.

**Vintage mismatch.** The DEM is 2016 lidar, the land cover is 2021. Ground
regraded between the two is described by one and not the other. Against the
alternative of a uniform coefficient this is a good trade, but it is a real
seam. (MRLC has also retired the epoch-based "legacy" NLCD in favour of
Annual NLCD Collection 1; moving to it is a live option for a later version.)

### What it does to the citywide numbers

Four bookmarks, same AOI, same 1 km halo, same 15 contributing chunks. v0.3
figures are the published `citywide/chicago_scenarios.json`; v0.4 is
`citywide_v04/`. Regenerate with `pipeline/compare_v04.py`; the artifact is
`data/derived/v04_comparison.json`.

| rung | v0.3 wet % | v0.4 wet % | Δ pts | v0.3 stored m³ | v0.4 stored m³ | change | v0.3 max m | v0.4 max m |
|---|---|---|---|---|---|---|---|---|
| 1.0″ nuisance | 2.33 | **1.32** | −1.01 | 1,356,787 | **813,378** | −40.1% | 4.65 | 4.57 |
| 3.34″ B75 2-yr | 10.04 | **11.57** | +1.53 | 9,268,766 | **11,953,175** | +29.0% | 7.44 | 7.77 |
| 7.58″ B70 100-yr | 14.42 | **16.39** | +1.97 | 17,749,785 | **23,527,367** | +32.6% | 7.91 | 8.05 |
| 8.57″ B75 100-yr | 15.02 | **16.89** | +1.87 | 19,271,816 | **25,325,684** | +31.4% | 7.95 | 8.05 |
| static full fill | 18.74 | 18.74 | 0.00 | 43,627,051 | 43,627,051 | 0.00% | 14.22 | 14.22 |

The mechanism, in mean net runoff over the 1,583 km² that drains to a pool:

| rung | v0.3 net (uniform) | v0.4 net (mean) | ratio | v0.4 loaded | v0.4 exported |
|---|---|---|---|---|---|
| 1.0″ | 4.0 mm | **2.0 mm** | ×0.51 | 3.2 Mm³ | 0.9 Mm³ |
| 3.34″ | 36.6 mm | **50.3 mm** | ×1.37 | 79.6 Mm³ | 49.1 Mm³ |
| 7.58″ | 95.9 mm | **153.6 mm** | ×1.60 | 243.2 Mm³ | 185.1 Mm³ |
| 8.57″ | 109.7 mm | **178.3 mm** | ×1.62 | 282.2 Mm³ | 219.9 Mm³ |

Three things to read out of that:

1. **The 1 in scenario roughly halves, and that is the headline correction.**
   A Chicago cell at the median CN of 92 sheds about 12 mm from an inch of
   rain; the 10 mm drainage term eats most of it. Under uniform C = 0.55 the
   same cell shed 14 mm regardless of what it was made of, so the old map
   showed nuisance ponding in places — parks, the lakefront, the forest
   preserve edges — that in the curve-number model produce essentially
   nothing at an inch. Wet area drops from 2.33% to 1.32% of the city. This
   is the initial abstraction doing its job, and it is also where the method
   is weakest: TR-55 warns that accuracy degrades below ~0.5 in of runoff,
   which is most of the city at this rung.
2. **The design storms get substantially wetter, and stored volume rises much
   less than loading does.** At 8.57 in the model now delivers 62% more water
   to pools, but stores only 31% more: 219.9 of the 282.2 Mm³ loaded is
   exported, because the pools that were going to fill were already filling.
   Chicago's terrain screening is **capacity-limited at the design storms and
   load-limited at the nuisance rain**, and v0.4 makes that split visible
   instead of hiding it inside one coefficient.
3. **Wet area moves less than volume.** +1.9 points at the two 100-year
   storms against +31% volume — the extra water mostly deepens pools that
   were already wet rather than finding new ones. That is the expected shape
   and a good sign: the map's *footprint* is a property of the terrain, and
   only its *depths* should be sensitive to the runoff model.

### Top pools by stored volume, 8.57″ (Bulletin 75 100-year)

The depression fill is identical between versions, so a pool's **footprint**
is the same in both rasters. The honest comparison is therefore: find the
pool on the v0.4 raster, then sum the v0.3 raster over that same footprint —
the same physical pool in both columns. Ranks are stable: refining 60 coarse
candidates instead of 20 returns the same ten in the same order.

| # | working name (nearest feature, not the pool's identity) | v0.3 m³ | v0.4 m³ | change | v0.4 max depth |
|---|---|---|---|---|---|
| 1 | South Kenwood Avenue, Marynook | 313,926 | 454,376 | +44.7% | 1.61 m |
| 2 | South Colfax Avenue, South Chicago | 283,055 | 400,966 | +41.7% | 1.85 m |
| 3 | West Ann Lurie Place, Archer Heights | 156,275 | 258,132 | +65.2% | 3.24 m |
| 4 | East 103rd Street, South Deering | 149,908 | 238,173 | +58.9% | 1.91 m |
| 5 | East 47th Drive, Kenwood | 135,608 | 208,501 | +53.8% | 2.57 m |
| 6 | East 84th Street, South Chicago | 141,664 | 206,265 | +45.6% | 1.36 m |
| 7 | West 60th Place, Clearing | 110,301 | 173,152 | +57.0% | 2.00 m |
| 8 | East 89th Street, Garden Homes | 113,187 | 172,996 | +52.8% | 1.63 m |
| 9 | West 63rd Street, West Englewood | 100,463 | 151,967 | +51.3% | 1.71 m |
| 10 | East 97th Street, Vet's Park | 109,864 | 146,223 | +33.1% | 1.39 m |

Every pool gains, by 33–65%, which is more than the citywide +31.4% — the
top pools are broad, shallow, heavily paved South and Southwest Side basins,
exactly the cells where the curve number diverges most from C = 0.55. This
list is worth reading against the ranking of the *static* layer, which is led
by the Eisenhower/Greektown trench at 2.24 Mm³. **The deepest bowl is not the
fullest one.** A trench is deep but narrow and collects only its own
right-of-way, so at 8.57 in it holds a small fraction of its capacity, while a
wide residential basin with a square kilometre of roofs and streets above it
fills. Any presentation of "biggest pool" has to say which question it is
answering: capacity, or how much water actually arrives.

### Mass balance, and what it cost

Every chunk checks, per rung, that `loaded = stored + exported` over its whole
domain (halo included). **60 (chunk, rung) checks, all closed: worst
|relative error| 1.4×10⁻¹⁴** against a 0.1% bug threshold; the citywide
roll-up worst case is 4.0×10⁻¹⁵. The static full fill reproduces v0.3 exactly,
citywide and per chunk, which is the check that the CN work did not touch the
geometry.

Compute, on a 10-core M-series laptop with 24 GB:

| stage | cost |
|---|---|
| fetch NLCD + SSURGO subsets, city (15 km margin) | 18 s |
| build the 30 m CN grid | 3 s |
| build 18 DEM-aligned 1 m CN tiles (36 MB total) | 44 s |
| 15 solved chunks + 3 skipped, 2 jobs | 3,788 s of chunk work, **1,937 s wall** |
| mosaic 4 scenario COGs (2.25 GB) to Drive | ~230 s |

Peak RSS **8.01 GB** per chunk, against ~6.6 GB at v0.3 — the cost of
carrying the curve-number array and the pool × CN histogram alongside
everything else. Per-chunk solve time is 123–339 s, essentially unchanged:
the fill and the D8 routing still dominate, and the loading step went from a
multiply to a matrix-vector product.

### Ladder support (roadmap 1b)

Rain depths are no longer hardcoded. `scenario.py --rungs
0.5,1,1.5,2,2.5,3.34,4,5,6,7.58,8.57,10` solves twelve; the default is still
the four labelled bookmarks. A rung that lands on a bookmark depth **keeps
the bookmark's id, label and provenance**, so a ladder is a superset of the
bookmarks rather than a parallel set of files and the viewer's existing
scenario ids keep working. `--rungs` and `--cn` reach chunk subprocesses
through the environment, so a chunked run cannot disagree with itself about
which rungs it is solving, and the aggregator takes its rung list from the
chunks rather than from a constant.

What makes a twelve-rung ladder affordable is the **pool × curve-number
histogram**: built once per chunk from the D8 result, which is then freed,
after which each rung is a matrix-vector product against a 101-entry runoff
lookup. Measured on the citywide chunks it is about 100,000 pools × 40–60
distinct curve numbers, a few tens of MB, and each extra rung costs well
under a second against the ~4 minutes the fill and routing take. A twelve-rung
citywide ladder should therefore cost roughly what this four-rung run did.

**The full ladder has deliberately not been run, and nothing has been
republished.** The live site still serves the v0.3 tiles; v0.4 lives in
`<data_root>/citywide_v04/` and the published `citywide/` folder is
untouched. The physics gets reviewed first — that is what Phase 1 is for.

### Known limits added at v0.4

Everything in the v0.2/v0.3 limits still holds. New ones that arrive with the
curve number:

- **It is an event-scale abstraction, not a process model.** No timing, no
  intensity, no antecedent moisture — this is the average antecedent runoff
  condition, one bucket of water per event. A dry August and a saturated
  April get the same map.
- **Ia = 0.2 S was generalised from agricultural watersheds**, and TR-55
  itself warns the implied initial loss "may not take place" in urban
  applications. It is the standard, and it is doing real work at the 1 in
  rung.
- **TR-55 says accuracy degrades below about 0.5 in of runoff**, which is
  most of the city at 1 in.
- **The soil and land cover are of a different decade than the DEM.**
- **D = 10 mm is still a guess.** It is now the only uniform term, which
  makes it more conspicuous rather than less important: at the 1 in rung it
  is most of the answer.
