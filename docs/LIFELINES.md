# Lifeline places — what was fetched, and what it misses

Roadmap Phase 2a. This is the ingest note for `data/lifelines/`: eight
categories of **public places** people depend on when a storm arrives, plus
the raw OSM road network that Phase 2b will test for passability.

Framing rule, restated from the roadmap and `AGENTS.md`: these files record
the **location of public places**. Nothing here describes the condition,
capacity, value, ownership or management of anything, and nothing downstream
may either. A hospital in this file is a door people need to reach, not an
entry in a register.

Retrieval provenance (URLs, dates, licenses) is in `data/SOURCES.md`;
per-category licensing is in `LICENSE-DATA.md`. Rebuild with:

    pipeline/fetch_lifelines.py                   # all eight categories
    pipeline/fetch_lifelines.py schools grocery   # a subset
    pipeline/fetch_roads_osm.py                   # road network -> Drive

---

## What was fetched

All counts are **inside the City of Chicago polygon** (`data/aoi/chicago.geojson`),
after clipping and deduplication, retrieved 2026-08-19.

| category | count | source |
|---|---:|---|
| `schools` | 856 | Chicago Data Portal (CPS SY2526) 645 + NCES private-school geocode 2023-24 211 |
| `fire_stations` | 92 | Chicago Data Portal 28km-gtjn |
| `police_stations` | 23 | Chicago Data Portal z8bn-74gv |
| `hospitals` | 33 | CMS Hospital General Information, geocoded |
| `pharmacies` | 142 | OpenStreetMap |
| `grocery` | 292 | OpenStreetMap |
| `substations` | 171 | OpenStreetMap |
| `water_wastewater` | 15 | OpenStreetMap |
| **total** | **1,624** | |

Subtype breakdowns:

- **schools** — 475 CPS elementary, 170 CPS high, 211 private.
- **hospitals** — 30 with an emergency department, 3 without. The ED flag is
  CMS's own `emergency_services` field, which is exactly the distinction
  Phase 2c needs when it runs isochrones "from fire stations and hospital
  EDs".
- **grocery** — 273 supermarkets, 15 greengrocers, 4 tagged plain `grocery`.
- **substations** — 71 traction (rail power), 25 transmission, 17
  distribution, 4 transition, 9 other, 45 with no `substation` subtag.
- **water_wastewater** — 13 `water_works` (purification plants, pumping
  stations, in-stream aeration), 2 `wastewater_plant`.

## Road network (Phase 2b input, not yet analysed)

**160,420 drivable OSM ways, 49.0 MB**, full `LineString` geometry, on Google
Drive at `<data_root>/lifelines_raw/chicago_roads_osm.geojson` (98 MB of
per-chunk Overpass cache sits beside it, 144 MB for the folder). No graph is
built and no routing is done — that is Phase 2b/2c.

See the "Road network — measured" section at the bottom for the class
histogram and what to watch out for.

---

## Standardisation rules

One `FeatureCollection` per category in `data/lifelines/`, EPSG:4326
(CRS84), **Point geometry only**, properties exactly:

| property | meaning |
|---|---|
| `name` | human-readable place name; `""` when the source has none |
| `category` | the file's category, repeated on every feature so merged files stay self-describing |
| `source` | short source key, resolvable in `data/SOURCES.md` |
| `source_id` | stable id within that source — portal row id, OSM `type/id`, CMS facility id, NCES PPIN |
| `retrieved` | ISO date the source was pulled |
| `subtype` | place kind within the category, verbatim from the source where one exists; `null` otherwise |

The rules behind those fields:

1. **Points, not outlines.** A lifeline place is somewhere to reach. OSM ways
   and relations collapse to their `center`; a substation yard's fence line
   is not information this project uses.
2. **Clipped to the city polygon, not the bounding box.** The AOI is a
   MultiPolygon with holes handled, so Norridge and Harwood Heights (enclaves
   surrounded by Chicago) are correctly excluded and the O'Hare corridor is
   correctly included. Verified against known points before the fetch.
3. **Deduplicated in two passes.** First on `(source, source_id)`, because
   Overpass returns an element once per sub-bbox it touches. Then on
   normalised name within 100 m, which catches the same place carried by two
   sources — that pass removed 8 schools listed by both CPS and NCES. Two
   campuses of the same school 2 km apart survive, as they should.
4. **Names are left as the source wrote them.** CPS publishes only
   `short_name`, so schools read `NOBLE - COMER` rather than a full title.
   Fire stations are named for their company (`Fire station E5`) because that
   is the only identifier the city publishes. No name is invented.
5. **Coordinates come from a cited geocoder, never by hand.** Where CMS's
   30-character `facility_name` is too mangled for any geocoder to resolve,
   the fix is a corrected *search string* in a documented table, not a typed
   latitude. One row needed it (La Rabida Children's Hospital).
6. **Rounded to 6 decimal places** (~0.1 m). More digits would be false
   precision on address-range geocodes.

---

## Coverage gaps — read this before plotting anything

Every category is incomplete in a different way. Where the gap can be
measured it is; where it cannot, that is said plainly rather than guessed.

### Substations — the worst gap, and unquantified

OSM `power=substation` is a volunteer mapping of a network nobody publishes.
171 features is *not* a census of Chicago's electrical substations:

- 71 of them are **traction** substations — CTA and Metra rail power, not the
  distribution grid. Real lifeline infrastructure, but a different system.
- Only 25 are tagged `transmission` and 17 `distribution`.
- **45 carry no `substation` subtag at all**, so their role is unknown.
- 42 have no name.

There is no authoritative public alternative. The HIFLD Open "Electric
Substations" layer, which the roadmap assumed, is gone (see below), and EIA's
public ArcGIS org publishes no substation service. Any Phase 2d styling of
this layer must say on the label that it is an OSM sample of unknown
completeness, not an inventory.

### HIFLD Open — no longer usable, checked 2026-08-19

The roadmap named HIFLD Open for several categories. It does not work any
more, and the full check is written up in `data/SOURCES.md` so nobody repeats
it. In summary:

- The hub site returns HTTP 200 but serves an empty ArcGIS Hub shell.
- The hosting org lists 526 feature services; **none** matches hospital,
  substation, wastewater, water treatment, pharmacy, school, fire station or
  law enforcement.
- The two surviving catalogue items are explicitly titled "(Deprecated
  HIFLDS)", and requesting the service behind either returns
  `{"error":{"code":400,"message":"Invalid URL"}}` — the record outlived the
  service.
- ArcGIS Online searches surface only third-party copies of the old layers,
  of unknown vintage and no authority.

EPA was tried as the replacement for treatment plants and also fell short:
Envirofacts FRS returns facilities but no coordinates, and ECHO listed only
4 Illinois facilities under NAICS 221320 and would not return coordinates
through its public endpoints. Hence OSM for that category too.

### Water and wastewater — the plants that matter are outside the city

15 features, of which only **2** are wastewater plants. That is not an OSM
failure; it is geography. Chicago's sewage is treated at MWRD plants that sit
mostly **outside** the city limits — Stickney (the largest in the world by
some measures) is in Stickney and Cicero, O'Brien is in Skokie. Only the
Calumet Water Reclamation Plant is inside the AOI, plus one unnamed
`wastewater_plant` way nearby at 41.668, −87.599.

The 13 `water_works` are the real story on the drinking-water side and are
well mapped: the Jardine and Eugene Sawyer purification plants, and the
Chicago Avenue, Western Avenue, Lakeview, Mayfair, Jefferson and North Branch
pumping stations.

**Implication for Phase 2:** a city-clipped lifelines layer cannot honestly
answer "does wastewater treatment stay reachable" — the answer lives in the
suburbs. When the analysis goes regional, refetch this category over
`data/aoi/region-cmap7.geojson`.

### Pharmacies — chains mapped, independents not

142 features, of which **124 (87%) are Walgreens or CVS** (90 and 34). Chain
stores are systematically mapped in OSM; independent and neighbourhood
pharmacies are not. The size of that shortfall is unmeasured — there is no
public register of Illinois retail pharmacy locations with coordinates that
was reachable in this pass — but a list where two chains are seven-eighths of
the total is plainly not a census. Treat this layer as "where the chain
pharmacies are", which is a real and useful thing, and not as pharmacy access.

### Grocery — likely the best OSM category here, still not complete

292 features, dominated by Jewel-Osco (37), Aldi (31), Mariano's (13), Whole
Foods (10), Cermak Fresh Market (9) and Pete's (8). `shop=convenience` was
deliberately excluded: corner stores are not grocery access. Small
independent groceries and *carnicerías* are under-represented for the same
reason independent pharmacies are. Two features carry no name.

### Schools — good coverage after adding the federal private-school file

CPS's own dataset covers district-run, charter and contract schools (645) and
nothing else. Private and parochial schools are a large share of Chicago
enrolment and appear in no city dataset, so they come from the NCES Private
School Universe Survey geocode file (211 kept after dedupe). Two caveats:

- NCES geocodes to the **reported address**, which for some schools is an
  administrative office rather than the campus. Block-accurate, not
  rooftop-accurate.
- The NCES private file is school year **2023-24** while CPS is **2025-26**,
  so a private school that closed or moved in the last two years may be
  stale.

Cross-check that raises confidence in the CPS layer: NCES's public-school
file for 2024-25 returns 656 schools in Chicago against CPS's 645.

### Fire stations — the data is 15 years old

92 stations, and the portal reports the rows last updated **2011-08-21**.
Chicago Fire Department station openings, closures and relocations since then
are simply not reflected. The count is plausible against CFD's published
company structure, but any individual station's location should be treated as
"as of 2011". No newer public citywide list was found.

### Police stations — district stations only

23 features: the 22 district stations plus Headquarters, last updated
2016-06-10. This is not every police facility in Chicago (no area
headquarters, no specialised units, no lockups). For the roadmap's purpose —
places people go for help — district stations are the right unit.

### Hospitals — Medicare-certified only, and the county line cuts

33 hospitals, 30 with an emergency department. What is missing:

- **Facilities not certified by Medicare** do not appear at all.
- **Freestanding emergency departments** are not separately listed; the ED
  flag attaches to hospitals.
- **Hospitals just outside the city limits that Chicagoans actually use** are
  clipped away — Advocate Christ in Oak Lawn, Evanston Hospital, and others.
  For access analysis this matters more than any in-city omission: the
  nearest ED to a South Side block may be outside the AOI. Phase 2c should
  run its isochrones against a hospital set fetched over a buffered AOI, not
  this city-clipped file.
- Three rows' coordinates come from OSM Nominatim rather than the Census
  geocoder, because CMS's address field for them is prose
  ("E 65TH ST AT LAKE MICHIGAN"). Those rows say so in `source` and carry an
  ODbL obligation — see `LICENSE-DATA.md`.

### Everything — one boundary, one date

Every file is clipped to the **city polygon**. For any question about
reaching a place, that boundary is arbitrary: water does not stop at Howard
Street and neither does an ambulance. Categories should be refetched over a
buffered or regional AOI before Phase 2c computes access deltas.

All eight files carry `retrieved: 2026-08-19`. They are a snapshot, and the
sources update on their own schedules — CPS annually, OSM continuously, CMS
quarterly, the two Chicago portal station layers apparently never.

---

## Road network — measured

`<data_root>/lifelines_raw/chicago_roads_osm.geojson`, retrieved 2026-08-19,
fetched by `pipeline/fetch_roads_osm.py` over a 5×5 grid of sub-bboxes.
`chicago_roads_osm.summary.json` beside it is the machine-readable version of
this section.

- **160,420 ways, 49.0 MB**, EPSG:4326 `LineString`, deduplicated by OSM way id.
- Extent: the AOI **bounding box** + 0.01°, `[-87.95011, 41.63454, -87.51414,
  42.03304]` — deliberately *not* clipped to the city polygon. A severed
  street two blocks over the line still cuts access into the city; clipping is
  the analysis step's decision, not the fetch's.
- Per-chunk Overpass responses are cached at
  `<data_root>/lifelines_raw/cache/roads_<r>_<c>.json` (98 MB), so a rerun
  after a failure refetches only what is missing. Overpass is someone else's
  free service.

By `highway` class:

| class | ways | | class | ways |
|---|---:|---|---|---:|
| `service` | 98,907 | | `motorway` | 1,536 |
| `residential` | 29,688 | | `motorway_link` | 1,408 |
| `secondary` | 15,577 | | `unclassified` | 939 |
| `tertiary` | 6,294 | | `trunk` | 408 |
| `primary` | 4,919 | | `primary_link` | 261 |
| `secondary_link` | 253 | | `trunk_link` | 130 |
| `tertiary_link` | 62 | | `living_street` | 38 |

Two things Phase 2b should know before using this:

1. **`service` is 62% of the file.** That is Chicago's alley grid plus parking
   aisles. Alleys genuinely flood and genuinely carry vehicles, so they were
   fetched rather than filtered at source — but a routing graph built over all
   160k ways will spend most of its edges on parking lots. Filter deliberately.
2. **1,806 ways are tagged `bridge` and 1,353 `tunnel`**, and `layer` is
   carried through where present. This is the tagging that separates a road
   deck *over* standing water from a viaduct *under* it. Given that the city's
   deepest pools are already at viaducts and underpasses, a passability pass
   that ignores `bridge`/`tunnel`/`layer` will sever exactly the roads that
   stay open and miss the ones that close.

Also carried per way, where OSM has it: `name`, `ref`, `oneway`, `maxspeed`,
`access`, `motor_vehicle`, `lanes`, `surface`.
