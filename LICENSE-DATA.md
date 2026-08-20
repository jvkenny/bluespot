# Data licensing

Two licenses, because the code and the maps have different ancestry.

| what | license |
|---|---|
| Everything in `pipeline/`, `viewer/`, `docs/` — the software | **MIT** (see `LICENSE`) |
| The derived map layers — ponding depth rasters and tiles, pool outlines and labels | **ODbL 1.0** |
| The lifeline place files in `data/lifelines/` | **per category, see below** |

## Why ODbL on the data

The elevation is **USGS 3DEP** — a work of the US government, public domain,
no restrictions. If that were the only input, this data would be public domain
too.

It is not the only input. OpenStreetMap water polygons are used as drainage
outlets in the fill (without them, bridge decks dam the rivers and the whole
basin floods), and OSM place names label the pools. OSM is licensed **ODbL**,
which carries a share-alike obligation onto derived databases. Rendered tiles
are plausibly a "Produced Work" needing only attribution, but the pool
GeoJSON carries OSM-derived names and geometry shaped by OSM inputs, so the
whole derived-data set is released under ODbL rather than claiming a cleaner
license we cannot fully support.

**Planned:** replace the OSM inputs with public-domain federal equivalents —
NHD (National Hydrography Dataset) for water, GNIS for names. That would make
every input public domain and let the data be re-released as CC0. Relicensing
toward CC0 later is straightforward; the reverse is not, which is why the
conservative license is the one shipping first.

## Lifeline places (`data/lifelines/`)

These are locations of public places — schools, stations, hospitals, shops,
plants. They are not one derived database, so they do not take one license.
Each file's `source` property names its origin; what that origin actually
states is recorded here, and the retrieval provenance is in `data/SOURCES.md`.

| file | source | what the source states |
|---|---|---|
| `schools.geojson` | Chicago Data Portal pb6d-zzuh (CPS) + NCES EDGE private-school geocode 2023-24 | Portal rows: license field reads "See Terms of Use". The City of Chicago Data Portal [Terms of Use](https://www.chicago.gov/city/en/narr/foia/data_disclaimer.html) publish these as open public records, free to use and redistribute, **as-is and without warranty**, and require that the City not be represented as endorsing the derived work. No share-alike clause. NCES rows: a work of the US federal government, **public domain**. |
| `fire_stations.geojson` | Chicago Data Portal 28km-gtjn | same as above |
| `police_stations.geojson` | Chicago Data Portal z8bn-74gv | same as above |
| `hospitals.geojson` | CMS Hospital General Information, geocoded | CMS Care Compare data is a work of the US federal government: **public domain**, no license asserted, but CMS must not be represented as endorsing anything. Coordinates for 30 of 33 rows come from the US Census Bureau geocoder (also public domain). The other 3 rows fall back to OSM Nominatim and say so in `source` — **those rows carry ODbL**, so the file as a whole is redistributed under ODbL until they are replaced. |
| `pharmacies.geojson` | OpenStreetMap | **ODbL 1.0**, © OpenStreetMap contributors |
| `grocery.geojson` | OpenStreetMap | **ODbL 1.0**, © OpenStreetMap contributors |
| `substations.geojson` | OpenStreetMap | **ODbL 1.0**, © OpenStreetMap contributors |
| `water_wastewater.geojson` | OpenStreetMap | **ODbL 1.0**, © OpenStreetMap contributors |
| `<data_root>/lifelines_raw/chicago_roads_osm.geojson` | OpenStreetMap | **ODbL 1.0**, © OpenStreetMap contributors. Lives on Google Drive, not in this repo. |

Practical consequence: anything computed from the OSM-sourced categories — the
Phase 2b road passability layer, the Phase 2c access-degradation surfaces — is
a derived database under ODbL and inherits share-alike, exactly like the
existing ponding layers. The three portal categories and (once the geocoder
fallback is resolved) hospitals could stand alone under weaker terms, but
Bluespot ships them alongside ODbL layers and does not attempt to split the
release.

HIFLD Open is deliberately absent. Its hosted layers for these categories no
longer resolve; the check performed on 2026-08-19 is written up in
`data/SOURCES.md` so it is not repeated.

## Attribution — required when reusing these layers

> Elevation and basemap: USGS The National Map (public domain).
> Water features and place names: © OpenStreetMap contributors, ODbL.
> Boundaries: US Census TIGER; City of Chicago Data Portal.
> Design-storm depths: Illinois State Water Survey Bulletins 70 and 75.
> Lifeline places: City of Chicago Data Portal; National Center for
> Education Statistics; Centers for Medicare & Medicaid Services; US Census
> Bureau geocoder; © OpenStreetMap contributors, ODbL.
> Derived ponding layers: Bluespot, ODbL.

## No warranty

These layers are terrain screening, not a hydraulic flood model or a
regulatory flood map. They are published for public understanding and are not
suitable for insurance, real-estate, or emergency decisions. Provided as-is,
without warranty of any kind.
