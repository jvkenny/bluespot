# Roadmap — from terrain screening to storm-impact screening

Design note, 2026-08-19. This plans the next four chapters. The constitution
holds throughout: public data only, every source cited in data/SOURCES.md,
"terrain screening, not flood prediction" (amended in Phase 4 to cover
forecasts honestly), no dollar-cost claims, describes places — never assets.

The destination: when a large storm is forecast, Bluespot highlights the
places and access routes that terrain suggests are at risk — hours to days
ahead, from public data, with every assumption on the label.

Dependency spine: Phase 1 gates everything (the depths must be defensible
before anything is built on them). Phase 2 gives forecasts something to
highlight. Phase 3 adds the river mechanism and can run in parallel after
Phase 1. Phase 4 is the payoff. Phase 5 lands when NOAA publishes.

---

## Phase 1 — Physics: earn the numbers (v0.4)

The current scenario model uses a uniform runoff coefficient C = 0.55 and a
uniform drainage-capacity term D = 10 mm. Both are urban-calibrated guesses;
C is simply wrong over the region's farmland. Fix before building anything
on top — this changes the published Chicago numbers, so do it before those
numbers get quoted.

**1a. Curve-number runoff grid.** Replace uniform C with the NRCS Curve
Number method — a 70-year-old, citable standard, not an invention:
- NLCD land cover + percent-impervious (MRLC, public domain)
- gSSURGO hydrologic soil groups (USDA, public domain)
- CN per cell; runoff Q = (P − 0.2S)² / (P + 0.8S), S = 1000/CN − 10 (in).
Runoff is computed per cell, then accumulated per catchment by the existing
D8 assignment. D stays a uniform, stated, adjustable assumption (the real
sewer network is not public data) — but it is now the *only* uniform term.

**1b. Scenario ladder.** Re-run citywide not just at the four bookmarks but
on a ladder of ~12 rain depths (0.5–10 in), so any forecast or user-chosen
depth becomes a lookup between precomputed rungs instead of a live solve.
Bookmarks (B75 2-yr, B70 100-yr, B75 100-yr) stay as labeled stops on the
ladder. Region gets a coarser ladder (4–6 rungs) after the city validates.

**1c. Validation against 311.** Chicago's water-in-street / water-in-basement
311 records (data portal) vs. pond footprints, stratified by rain rung using
observed storm totals. Publish hit/miss rates in METHOD.md — whatever they
are. This is the credibility gate for Phase 4; a screening tool that has
never been scored against observations must not highlight forecasts.

**1d. Republish.** Updated citywide numbers with a visible changelog note
("v0.4: spatially varying runoff replaces uniform C — here's what changed
and why"). Then the ~13 h regional scenario run, now with defensible physics.

## Phase 2 — Lifelines: what stays reachable

The impact layer. All inputs are public *places* and public geometry.

**2a. Lifeline places.** Schools, fire and police stations, hospitals/EDs,
pharmacies, grocery stores, electrical substations, water and wastewater
treatment plants — from HIFLD Open, the Chicago Data Portal, and OSM, each
cited. Stored as a small GeoJSON per category with source + retrieval date.

**2b. Road passability.** Intersect each ladder rung's depth raster with OSM
road centerlines. A segment is severed when ponded depth exceeds a stated
passability threshold (~30 cm, cited to FHWA/NWS vehicle-stall guidance;
threshold adjustable and on the label). Viaducts and underpasses — already
the city's deepest pools — become the visible stars, which matches lived
experience of every Chicago flood.

**2c. Access degradation.** Per rung, travel-time isochrones from fire
stations and hospital EDs over the severed network vs. the dry network;
per-block access delta. Start with a plain Dijkstra over the OSM graph —
no routing service dependency.

**2d. Viewer "Impact" mode.** Lifelines colored ok / access-degraded /
ponded-adjacent; severed segments highlighted; the rain control drives it.
New tour chapter: what stays reachable as the storm grows.

Framing rule, restated: exposure and access of public places. Never asset
condition, never cost estimates.

## Phase 3 — Wider hydrology: the river mechanism (fluvial)

Everything so far is pluvial — rain landing on terrain. Rivers responding to
their watersheds are a different mechanism and must be labeled as such.

**3a. NHD swap.** Replace OSM water polygons with NHDPlus HR as the outlet
source. Also removes the last ODbL input — derived data can move to CC0.

**3b. HAND.** Height Above Nearest Drainage from the existing DEM mosaic +
NHD flowlines, per catchment. Same chunked discipline as everything else.

**3c. Stage from discharge.** Synthetic rating curves per reach (the NOAA
OWP method: hydraulic geometry from HAND + Manning), driven by National
Water Model discharge (NWM on AWS Open Data, per-reach feature_id =
NHDPlus comid). Calibrate against USGS gauges (Des Plaines, Salt Creek,
Calumet) using the NWM v3 retrospective before trusting any forecast.

**3d. Layer + labeling.** "River flooding" as a distinct layer with its own
method note. The Des Plaines and Calumet valleys — where the pluvial model's
halo bias concentrates — are exactly where this layer earns its keep.

## Phase 4 — Storm Watch: the forecast mode

The killer feature, and the constitutional amendment. Framing: **forecast
screening** — "if this forecast verifies, terrain suggests water collects
here" — always shown alongside a link to official NWS alerts
(api.weather.gov), never presented as a warning system.

**4a. Rain forecast → ladder lookup.** Open-Meteo forecast API (hourly QPF,
7+ days; ensemble endpoint for spread). Aggregate rolling 24/48 h event
windows; map the forecast band to the bracketing ladder rungs — "Saturday's
forecast: 2.1–3.4 in / 24 h → between these two maps." No live compute;
the ladder from Phase 1 makes this a static lookup.

**4b. River forecast.** NWM short-range (18 h) and medium-range (10 day)
discharge through the Phase 3 rating curves → fluvial highlight.

**4c. Impact watch.** Lifelines and road segments whose state changes at
the forecast rung get a "watch" flag — the hours-to-days-ahead answer to
"which of the systems we depend on might be affected."

**4d. Delivery.** A Storm Watch banner in the viewer when a forecast window
crosses the lowest interesting rung; a small poller (cron) that can push a
notification when thresholds are crossed. Public site stays pull-based.

**4e. Honesty amendments.** The site-wide disclaimer gains a forecast
clause; Storm Watch displays QPF uncertainty (ensemble spread), the
validation scores from 1c, and the NWS link, always. Known gotchas to
carry into implementation: Open-Meteo's daily array starts at *yesterday*;
all storm-window math in America/Chicago, not UTC.

## Phase 5 — Atlas 15: the futures bookmark

NOAA Atlas 15 preliminary CONUS data entered public peer review in early
2026 with publication anticipated later in 2026 (Volume 1 = historically
adjusted, Volume 2 = future climate-adjusted). When Illinois grids are
available: add the mid-century bookmark(s), labeled provisional until
final publication. The headline story then reads on one block:
**1963 design storm → today's → mid-century's** — the design-storm gap,
past to future.

---

## Cost notes

- Ladder compute: ~12 citywide rungs at roughly the current per-scenario
  cost (~15 min chunked each); PMTiles growth on the order of 5–8 GB to R2.
  Region ladder is the big one — run it last, coarse, after city validates.
- New raw inputs (NLCD, gSSURGO, NHDPlus HR, HIFLD): a few GB, Drive-first
  per the data policy, each with a SOURCES.md entry before first use.
- NWM: forecast files fetched on demand, never archived locally beyond a
  rolling window; retrospective pulled per-gauge for calibration only.
