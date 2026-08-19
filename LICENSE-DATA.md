# Data licensing

Two licenses, because the code and the maps have different ancestry.

| what | license |
|---|---|
| Everything in `pipeline/`, `viewer/`, `docs/` — the software | **MIT** (see `LICENSE`) |
| The derived map layers — ponding depth rasters and tiles, pool outlines and labels | **ODbL 1.0** |

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

## Attribution — required when reusing these layers

> Elevation and basemap: USGS The National Map (public domain).
> Water features and place names: © OpenStreetMap contributors, ODbL.
> Boundaries: US Census TIGER; City of Chicago Data Portal.
> Design-storm depths: Illinois State Water Survey Bulletins 70 and 75.
> Derived ponding layers: Bluespot, ODbL.

## No warranty

These layers are terrain screening, not a hydraulic flood model or a
regulatory flood map. They are published for public understanding and are not
suitable for insurance, real-estate, or emergency decisions. Provided as-is,
without warranty of any kind.
