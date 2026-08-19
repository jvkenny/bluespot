# Publishing checklist (not done yet — repo is private by design)

The viewer is static HTML; the weight is in the PMTiles archives (2.2 GB
today, more once regional rain scenarios exist). GitHub Pages caps files at
100 MB and repos near 1 GB, so the tiles must be served from object storage
that supports **HTTP Range** and **CORS**. Cloudflare R2 fits: free tier is
10 GB stored, and egress is free — the reason a public map here does not
become a bandwidth bill.

## Blocking steps (John, in the Cloudflare dashboard)
1. Create a bucket, e.g. `bluespot`. Do **not** reuse the First Return bucket:
   that one's access model is unguessable paths, this one is deliberately
   public. (Confirmed 2026-08-18: the existing First Return token is scoped to
   its own bucket and cannot create or list others.)
2. Enable public access (r2.dev URL, or attach a custom domain).
3. CORS: allow `GET`, `HEAD` from the site origin, expose `Content-Length`,
   `Content-Range`, `ETag`; allow the `Range` request header.
4. Create an **API token scoped to that bucket only**, then write
   `.env.publish` in the repo root (gitignored) with the keys listed at the
   top of `pipeline/publish_r2.sh`.

Then: `pipeline/publish_r2.sh --dry-run`, then for real, then set
`window.BLUESPOT_DATA_BASE` in `viewer/config.js` to the public base and
verify the viewer loads with the local `viewer/data` symlink removed.

## Content still to settle before the repo goes public
- **Pool names are raw Nominatim** nearest-feature labels; some are misleading
  ("North Mozart Street" for a schoolyard). Curate the top-40/60 by hand.
- **Licensing.** Code and derived data need separate answers. The depth
  rasters derive from USGS 3DEP (public domain) but use OSM water polygons as
  a processing input and OSM names as labels, so the derived layers are
  plausibly subject to ODbL share-alike. Decide deliberately; do not ship
  without an explicit statement.
- **Attribution** already renders in the viewer (USGS, OSM/Nominatim, Census
  TIGER, Chicago Data Portal, Esri basemap, ISWS bulletins) — keep it there.
- **Caveats that must survive the move to a public audience**: terrain
  screening not flood prediction; quarries are the deepest "pools"; west Will
  County has no 1 m coverage; rain scenarios are Chicago-only until the
  regional run lands; a 2016 construction pit is the citywide max depth.
- Basemap terms: Esri World Topographic tiles are used via the public ArcGIS
  Online endpoint — confirm that is acceptable for a public site, or swap to
  an OSM-based raster/vector basemap.

## Status log
- **2026-08-18** — Bucket `bluespot` created (ENAM), CORS set, Public
  Development URL enabled, bucket-scoped token in `.env.publish`. Citywide
  archives uploaded (513 MB, 6 files) and verified over the public URL:
  `206 Partial Content`, `Access-Control-Allow-Origin: *`,
  `Access-Control-Expose-Headers: content-length,content-range,etag`,
  week-long immutable caching. Regional pair (1.7 GB) uploading.
  Still private: nothing links to the bucket, `viewer/config.js` still points
  at the local symlink, and the repo remains private.
