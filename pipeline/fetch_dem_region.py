#!/usr/bin/env python3
"""Fetch USGS 3DEP 1m DEM tiles for a multi-county region via the TNM Access
API. Unlike fetch_dem.py (single project, <=100 results), this handles:

- paging past the TNM 100-item cap
- filtering candidate tiles by true intersection with the AOI polygons (the
  region bbox otherwise drags in Lake Michigan, NW Indiana and SE Wisconsin)
- MULTIPLE overlapping lidar projects/vintages. Across the 7-county CMAP
  region each 10 km cell is offered by 1-3 acquisitions. A priority list
  (PRIORITY) picks ONE project per cell, so vintage seams follow acquisition
  boundaries deliberately instead of checkerboarding cell by cell.
  IL_4_County_QL1_LiDAR_2016 ranks first because it alone covers ~85% of the
  region as a single consistent acquisition, and it is the acquisition the
  Chicago citywide product was built from — pinning it keeps the regional
  product byte-identical with the citywide one over the city.
  Projects not in PRIORITY rank below every listed one, newest publication
  date first.

Usage:
  fetch_dem_region.py <aoi.geojson> --plan            # report + write plan, no download
  fetch_dem_region.py <aoi.geojson>                   # download per the plan
Writes tiles to <data_root>/dem/ (idempotent; same folder as the citywide
tiles) and appends provenance (project + publicationDate) to MANIFEST.jsonl.
The plan is written to <data_root>/regional/dem_plan.json.
"""
import json, os, re, sys, datetime, time, urllib.request, urllib.parse
import numpy as np
from paths import data_root

TNM = "https://tnmaccess.nationalmap.gov/api/v1/products"
DATASET = "Digital Elevation Model (DEM) 1 meter"

# Highest-priority first; substring match against the project name.
PRIORITY = [
    "IL_4_County_QL1_LiDAR_2016",  # 2016 QL1, ~85% of the region, = citywide
    "IL_10CountyNRCS_D23",         # 2023, fills the western/southern fringe
    "IL_MidNorth_D22",             # 2022
]

GRID_RES = 0.002   # deg, ~200 m: AOI rasterization for intersection tests


def aoi_grid(aoi_path, res=GRID_RES):
    """Rasterize the AOI (EPSG:4326) to a coarse bool grid for cheap tile-bbox
    intersection tests. Returns (grid, (x0,y0,x1,y1), res)."""
    from rasterio.features import rasterize
    from rasterio.transform import from_origin
    gj = json.load(open(aoi_path))
    geoms = [f["geometry"] for f in gj["features"]]
    xs, ys = [], []
    def walk(c):
        if isinstance(c[0], (int, float)): xs.append(c[0]); ys.append(c[1])
        else:
            for k in c: walk(k)
    for g in geoms: walk(g["coordinates"])
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w = int(np.ceil((x1 - x0) / res)); h = int(np.ceil((y1 - y0) / res))
    grid = rasterize(geoms, out_shape=(h, w), transform=from_origin(x0, y1, res, res),
                     fill=0, default_value=1, dtype="uint8").astype(bool)
    return grid, (x0, y0, x1, y1), res


def _cells(gb, res, shape, bb):
    """Grid row/col slice covered by a lon/lat bbox (minX,minY,maxX,maxY)."""
    x0, y0, x1, y1 = gb
    h, w = shape
    c0 = max(int((bb[0] - x0) / res), 0); c1 = min(int(np.ceil((bb[2] - x0) / res)), w)
    r0 = max(int((y1 - bb[3]) / res), 0); r1 = min(int(np.ceil((y1 - bb[1]) / res)), h)
    return r0, r1, c0, c1


def bbox_intersects(grid, gb, res, bb):
    r0, r1, c0, c1 = _cells(gb, res, grid.shape, bb)
    if c0 >= c1 or r0 >= r1:
        return False
    return bool(grid[r0:r1, c0:c1].any())


def fetch_all(bbox):
    """Page through every TNM product for the bbox (API caps `max` at 100)."""
    items, offset = [], 0
    while True:
        q = urllib.parse.urlencode({"datasets": DATASET, "bbox": bbox,
            "outputFormat": "JSON", "max": "100", "offset": str(offset)})
        for attempt in range(5):
            try:
                r = json.load(urllib.request.urlopen(f"{TNM}?{q}", timeout=180))
                break
            except Exception as ex:
                print(f"  TNM offset {offset}: {ex}; retrying")
                time.sleep(10 * (attempt + 1))
        else:
            sys.exit("TNM API failed")
        items += r["items"]
        total = r.get("total", len(items))
        offset += len(r["items"])
        print(f"  TNM: {len(items)}/{total}")
        if offset >= total or not r["items"]:
            break
    return items


# TNM uses two title formats for 1 m DEM tiles; both must parse:
#   "USGS 1 Meter 16 x42y462 IL_4_County_QL1_LiDAR_2016_B16"  (zone given)
#   "USGS one meter x39y465 IL 12-County-KaneCo 2008"         (older, no zone)
# The 10 km cell key is (x, y): the whole CMAP region is UTM 16N, so the zone
# is informational only (asserted below), not part of the key — otherwise the
# two formats would split one physical cell into two.
CELL_RE = re.compile(r"\b(?:(\d{1,2})\s+)?x(\d+)y(\d+)\b")


def parse(it):
    """-> ((x, y), project_name, utm_zone_or_None) from the product title."""
    m = CELL_RE.search(it["title"])
    if not m:
        return None
    cell = (int(m.group(2)), int(m.group(3)))
    zone = int(m.group(1)) if m.group(1) else None
    proj = it["title"].split(m.group(0))[-1].strip().lstrip("_ ")
    return cell, proj, zone


def rank(proj, pubdate):
    """Sort key: PRIORITY order first, then unlisted projects newest-first."""
    for i, p in enumerate(PRIORITY):
        if p in proj:
            return (0, i, ())
    # negate each character so ascending sort = newest publication date first
    return (1, 0, tuple(-ord(c) for c in (pubdate or "")))


def plan(aoi_path):
    grid, gb, res = aoi_grid(aoi_path)
    print(f"AOI grid {grid.shape}, {grid.sum():,} cells "
          f"(~{grid.sum() * 200 * 200 / 1e6:,.0f} km2 at {res} deg)")
    items = fetch_all(f"{gb[0]},{gb[1]},{gb[2]},{gb[3]}")

    cells, n_out, n_bad = {}, 0, 0
    for it in items:
        p = parse(it)
        if not p:
            print("  unparseable title:", it["title"]); n_bad += 1; continue
        bb = it.get("boundingBox") or {}
        if bb and not bbox_intersects(grid, gb, res,
                (bb["minX"], bb["minY"], bb["maxX"], bb["maxY"])):
            n_out += 1; continue
        if p[2] not in (None, 16):
            print(f"  UTM zone {p[2]} outside 16N, skipped: {it['title']}")
            n_bad += 1; continue
        cells.setdefault(p[0], []).append((p[1], it))
    print(f"{len(items)} products from TNM; {n_out} outside the AOI polygons; "
          f"{n_bad} unparseable; {len(cells)} distinct 10 km cells")

    chosen, by_proj, alts = [], {}, {}
    for cell, cands in sorted(cells.items()):
        cands.sort(key=lambda c: rank(c[0], c[1].get("publicationDate")))
        proj, it = cands[0]
        chosen.append({"cell": list(cell), "project": proj, "title": it["title"],
                       "url": it["downloadURL"],
                       "publicationDate": it.get("publicationDate"),
                       "sizeInBytes": it.get("sizeInBytes") or 0,
                       "boundingBox": it.get("boundingBox"),
                       "alternatives": sorted({c[0] for c in cands[1:]})})
        by_proj[proj] = by_proj.get(proj, 0) + 1
        for p2, _ in cands[1:]:
            alts[p2] = alts.get(p2, 0) + 1

    print("\nCHOSEN project -> #cells (publication date)")
    dates = {}
    for c in chosen:
        dates.setdefault(c["project"], set()).add((c["publicationDate"] or "?")[:10])
    for p, n in sorted(by_proj.items(), key=lambda x: -x[1]):
        print(f"  {n:4d}  {p:42s} {','.join(sorted(dates[p]))}")
    print("available but NOT chosen -> #cells")
    for p, n in sorted(alts.items(), key=lambda x: -x[1]):
        print(f"  {n:4d}  {p}")

    # coverage gap check, per county. NOTE the AOI is the *legal* county
    # polygons, so Cook and Lake extend far out into Lake Michigan where no
    # DEM exists and none should; those gaps are expected. A gap much larger
    # than a county's AWATER is a real hole in 3DEP 1 m DEM coverage.
    from rasterio.features import rasterize
    from rasterio.transform import from_origin
    cov = np.zeros(grid.shape, dtype=bool)
    for c in chosen:
        bb = c["boundingBox"]
        if not bb: continue
        r0, r1, c0, c1 = _cells(gb, res, grid.shape,
                                (bb["minX"], bb["minY"], bb["maxX"], bb["maxY"]))
        cov[r0:r1, c0:c1] = True
    km2 = res * 111.0 * res * 111.0 * np.cos(np.deg2rad(41.8))   # ~ km2/cell
    tr = from_origin(gb[0], gb[3], res, res)
    print(f"\nCOVERAGE by county (AOI = legal polygon, incl. lake water)")
    print(f"  {'county':10s} {'AOI km2':>9s} {'gap km2':>9s} {'AWATER':>9s}  note")
    for f in json.load(open(aoi_path))["features"]:
        m = rasterize([f["geometry"]], out_shape=grid.shape, transform=tr,
                      fill=0, default_value=1, dtype="uint8").astype(bool)
        gap = int((m & ~cov).sum()) * km2
        aw = f["properties"].get("AWATER", 0) / 1e6
        note = "ok" if gap <= aw * 1.1 + 20 else f"REAL GAP ~{gap - aw:,.0f} km2"
        print(f"  {f['properties']['NAME']:10s} {m.sum()*km2:9,.0f} {gap:9,.0f} "
              f"{aw:9,.0f}  {note}")
    uncov = int((grid & ~cov).sum())
    print(f"  region: {100 * (grid & cov).sum() / grid.sum():.2f}% of the AOI "
          f"polygon area ({uncov * km2:,.0f} km2 uncovered, mostly Lake Michigan)")
    tot = sum(c["sizeInBytes"] for c in chosen)
    print(f"{len(chosen)} tiles chosen, {tot / 2**30:.1f} GB")
    return chosen


def main(aoi_path, plan_only=False):
    chosen = plan(aoi_path)
    reg = os.path.join(data_root(), "regional")
    os.makedirs(reg, exist_ok=True)
    with open(os.path.join(reg, "dem_plan.json"), "w") as f:
        json.dump({"aoi": os.path.basename(aoi_path),
                   "planned": datetime.date.today().isoformat(),
                   "priority": PRIORITY, "tiles": chosen}, f, indent=1)
    print(f"plan -> {reg}/dem_plan.json")
    if plan_only:
        return

    raw = os.path.join(data_root(), "dem")
    os.makedirs(raw, exist_ok=True)
    have = fail = got = 0
    for i, c in enumerate(chosen):
        url = c["url"]
        dest = os.path.join(raw, os.path.basename(url))
        want = c["sizeInBytes"]
        if os.path.exists(dest) and (not want or os.path.getsize(dest) == want):
            have += 1; continue
        print(f"  get  [{i+1}/{len(chosen)}] {os.path.basename(dest)} "
              f"({want/1e6:.0f} MB)", flush=True)
        for attempt in range(4):
            try:
                urllib.request.urlretrieve(url, dest + ".part")
                break
            except Exception as ex:
                print(f"    {ex}; retrying", flush=True)
                time.sleep(15 * (attempt + 1))
        else:
            print(f"    FAILED {url}", flush=True); fail += 1; continue
        os.replace(dest + ".part", dest); got += 1
        with open(os.path.join(raw, "MANIFEST.jsonl"), "a") as m:
            m.write(json.dumps({"file": os.path.basename(dest), "source": url,
                "title": c["title"], "project": c["project"],
                "publicationDate": c["publicationDate"],
                "retrieved": datetime.date.today().isoformat()}) + "\n")
    print(f"done: {got} downloaded, {have} already present, {fail} failed")


if __name__ == "__main__":
    main(sys.argv[1], plan_only="--plan" in sys.argv)
