# Back pocket — FEMA RAPT datasets (noted 2026-08-17)

RAPT (Resilience Analysis & Planning Tool,
https://experience.arcgis.com/experience/0a317e8998534c30a9b2d3861c814d42/)
is FEMA's census-tract dashboard for emergency managers: 100+ layers, no
terrain mechanism, no street scale. Not a competitor — a *donor*. Its
underlying datasets are public and could later give bluespot layers their
human context. Source: RAPT User Guide (FEMA, 2023 ed. read 2026-08-17;
2025 ed. exists at fema.gov, 403 to scripts).

## What's inside worth remembering

1. **CRCI + 22 community-resilience-challenge indicators** (Census/ACS;
   county + tract). Poverty, no-vehicle households, limited English,
   single-parent, no-broadband, unemployment, income inequality, disability,
   65+, rental cost burden, etc. Authoritative list: user guide §6.1 graphic
   + FEMA CRCI methodology doc.
   → *Value-add join: "who lives in the bowls" — overlay high-challenge
   tracts on pool density / heat exposure. RAPT knows who is vulnerable but
   not where water goes; we know where water goes but not who. Nobody has
   the join at 1 m.*
2. **HIFLD Open infrastructure points** (public domain,
   https://hifld-geoplatform.opendata.arcgis.com/): schools, hospitals,
   fire stations…
   → *"what sits in the bowls" — public facilities inside deep pools.
   Still places-not-assets: locations, not asset registries.*
3. **National Flood Hazard Layer** (FEMA NFHL; zoom-gated in RAPT).
   → *the truth-gap visual: parcels outside the mapped 1% zone but inside a
   deep terrain bowl — the Field Atlas source 9 story (75k+ Chicago
   properties), made visible per block.*
4. **Hazard/forecast layers**: NOAA real-time radar + watches/warnings, live
   stream gauges, historic tornado/hurricane tracks, seismic + flood risk
   (likely National Risk Index — verify), 4–6 ft sea-level-rise forecast.
   → *mostly out of scope; stream gauges maybe for event validation.*

## Rules if ever used
Each dataset gets its own SOURCES.md entry with vintage + retrieval date at
ingest time (RAPT is a pointer, not a source). Tract indicators are context
UNDER our layers, never presented as our findings; CRCI methodology has
known critiques — read FEMA's methodology doc before leaning on the
composite index rather than single indicators.
