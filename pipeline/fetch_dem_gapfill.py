#!/usr/bin/env python3
"""Second pass over the regional DEM: fill cells the first pass under-covered.

WHY THIS EXISTS. fetch_dem_region.py picks one lidar project per 10 km cell
from a priority list, to keep vintages consistent. That is the right policy
and it has one bad failure mode: TNM will happily list a product for a cell
that is *almost entirely nodata* — a tile at the ragged edge of its
acquisition. Pick that one and the cell comes out empty even though a
different project offers a full tile for the same ground. Measured after the
first regional fill: 2,923 km2 of AOI land had no elevation, and 1,672 km2
of that sat in cells with an untried alternative. DuPage County came out 53%
covered; it should be ~100%.

The fix is not to re-rank by vintage but to COMPOSITE. This script downloads
the alternatives for under-covered cells, and `bluespot_region.py` then
orders the VRT so the preferred acquisition is drawn LAST (on top) with
lower-priority projects beneath it. GDAL treats a source's nodata pixels as
transparent, so the preferred vintage wins everywhere it actually has data
and the fallbacks show through only in its holes. Vintage consistency is
preserved where it is achievable and coverage wins where it is not.

Cost: a seam can now fall *inside* a 10 km cell rather than only on cell
boundaries. That is a strictly better trade than a hole, and it is recorded
per tile in MANIFEST.jsonl either way.

Usage:
  fetch_dem_gapfill.py <aoi.geojson> <gap_cells.json> [--plan] [min_gap_km2]
"""
import json, os, sys, time, datetime, urllib.request
from paths import data_root
import fetch_dem_region as R


def main(aoi_path, gap_path, plan_only=False, min_gap=3.0):
    gaps = {tuple(g["cell"]): g for g in json.load(open(gap_path))
            if g["gap_km2"] >= min_gap and g["alternatives"]}
    print(f"{len(gaps)} under-covered cells with at least one alternative "
          f"(gap >= {min_gap} km2), {sum(g['gap_km2'] for g in gaps.values()):,.0f} km2")

    grid, gb, res = R.aoi_grid(aoi_path)
    items = R.fetch_all(f"{gb[0]},{gb[1]},{gb[2]},{gb[3]}")
    cands = {}
    for it in items:
        p = R.parse(it)
        if not p or p[2] not in (None, 16):
            continue
        cands.setdefault(p[0], []).append((p[1], it))

    raw = os.path.join(data_root(), "dem")
    want = []
    for cell, g in sorted(gaps.items(), key=lambda kv: -kv[1]["gap_km2"]):
        chosen = g["project"]
        for proj, it in sorted(cands.get(cell, []),
                               key=lambda c: R.rank(c[0], c[1].get("publicationDate"))):
            if proj == chosen:
                continue                      # already downloaded, it is the hole
            dest = os.path.join(raw, os.path.basename(it["downloadURL"]))
            if os.path.exists(dest):
                continue
            want.append((cell, g["gap_km2"], proj, it))

    tot = sum((it.get("sizeInBytes") or 0) for _, _, _, it in want)
    print(f"\n{len(want)} alternative tiles to fetch, {tot/2**30:.1f} GB")
    for cell, gk, proj, it in want:
        print(f"  x{cell[0]}y{cell[1]}  gap {gk:5.1f} km2  <- {proj}")
    if plan_only:
        return

    got = fail = 0
    for i, (cell, gk, proj, it) in enumerate(want):
        url = it["downloadURL"]
        dest = os.path.join(raw, os.path.basename(url))
        sz = it.get("sizeInBytes") or 0
        print(f"  get [{i+1}/{len(want)}] {os.path.basename(dest)} ({sz/1e6:.0f} MB)",
              flush=True)
        for attempt in range(4):
            try:
                urllib.request.urlretrieve(url, dest + ".part"); break
            except Exception as ex:
                print(f"    {ex}; retrying", flush=True); time.sleep(15 * (attempt + 1))
        else:
            print(f"    FAILED {url}", flush=True); fail += 1; continue
        os.replace(dest + ".part", dest); got += 1
        with open(os.path.join(raw, "MANIFEST.jsonl"), "a") as m:
            m.write(json.dumps({"file": os.path.basename(dest), "source": url,
                "title": it["title"], "project": proj,
                "publicationDate": it.get("publicationDate"),
                "role": "gapfill", "fills_cell": list(cell),
                "retrieved": datetime.date.today().isoformat()}) + "\n")
    print(f"done: {got} downloaded, {fail} failed")


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    main(a[0], a[1], plan_only="--plan" in sys.argv,
         min_gap=float(a[2]) if len(a) > 2 else 3.0)
