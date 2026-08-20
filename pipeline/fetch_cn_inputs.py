#!/usr/bin/env python3
"""Fetch the two public inputs the curve-number grid needs (data/SOURCES.md
#9, #10, #11), as AOI subsets rather than CONUS-wide downloads.

  1. NLCD 2021 Land Cover (L48) and NLCD 2021 Percent Developed
     Imperviousness (L48), 30 m EPSG:5070, from the MRLC WCS. The request is
     a bounding-box subset snapped to the NLCD grid, so the two rasters land
     cell-for-cell on each other with no resampling.
  2. SSURGO map-unit polygons from the NRCS Soil Data Access WFS, plus the
     `component.hydgrp` attribute per map unit from the SDA tabular REST
     endpoint, aggregated to one hydrologic soil group per map unit by
     dominant component.

Everything lands on the Drive data root (pipeline/paths.py) —
`<data_root>/landcover/` and `<data_root>/soils/` — each with a
MANIFEST.jsonl recording url, request, bytes, sha256 and retrieval time.
Re-running is idempotent: an existing output of non-zero size is kept unless
--force is given.

Usage:
  fetch_cn_inputs.py <aoi.geojson> <name> [margin_m] [--force]

The margin must be wide enough to cover the whole DEM *mosaic*, not just the
AOI: the mosaic is whole 10 km USGS tiles plus a 1 km scenario halo, so it can
reach ~11 km past the AOI bounding box, and every one of those cells sheds
runoff into pools inside the city. 15 km is the safe default.

e.g.  fetch_cn_inputs.py data/aoi/chicago.geojson chicago 15000
      fetch_cn_inputs.py data/aoi/region-cmap7.geojson region 15000
"""
import hashlib, json, os, subprocess, sys, time, urllib.parse, urllib.request

import rasterio
from rasterio.warp import transform as rio_transform

from paths import data_root

GDAL = "/opt/homebrew/bin"

# ---------------------------------------------------------------- sources --
WCS = "https://www.mrlc.gov/geoserver/mrlc_download/wcs"
NLCD_LAYERS = {
    "landcover":  "mrlc_download__NLCD_2021_Land_Cover_L48",
    "impervious": "mrlc_download__NLCD_2021_Impervious_L48",
}
# NLCD grid origin (upper-left) and cell size in EPSG:5070, from the WCS
# DescribeCoverage of the layers above. Subsets are snapped to it.
NLCD_ORIGIN = (-2493045.0, 3310005.0)
NLCD_RES = 30.0

SDA_WFS = "https://SDMDataAccess.sc.egov.usda.gov/Spatial/SDMWGS84Geographic.wfs"
SDA_TABULAR = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"
# The WFS refuses a BBOX bigger than this (its own error message states the
# number in square metres). Stay well under it and tile the AOI.
WFS_MAX_BBOX_M2 = 10.1e9
WFS_TILE_BUDGET_M2 = 6.0e9
MUKEY_BATCH = 400          # mukeys per SDA tabular query


def _log(*a):
    print(*a, flush=True)


def aoi_bounds_4326(aoi_path):
    gj = json.load(open(aoi_path))
    xs, ys = [], []

    def walk(c):
        if isinstance(c[0], (int, float)):
            xs.append(c[0]); ys.append(c[1])
        else:
            for k in c:
                walk(k)
    for f in gj["features"]:
        walk(f["geometry"]["coordinates"])
    return min(xs), min(ys), max(xs), max(ys)


def manifest(dirpath, rec):
    with open(os.path.join(dirpath, "MANIFEST.jsonl"), "a") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")


def sha256(path, cap=None):
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
            n += len(blk)
            if cap and n >= cap:
                break
    return h.hexdigest()


# ------------------------------------------------------------------ NLCD ---
def snap_bbox_5070(x0, y0, x1, y1):
    """Grow a 5070 bbox out to the NLCD 30 m grid lines."""
    ox, oy = NLCD_ORIGIN
    import math
    sx0 = ox + NLCD_RES * math.floor((x0 - ox) / NLCD_RES)
    sx1 = ox + NLCD_RES * math.ceil((x1 - ox) / NLCD_RES)
    sy0 = oy - NLCD_RES * math.ceil((oy - y0) / NLCD_RES)
    sy1 = oy - NLCD_RES * math.floor((oy - y1) / NLCD_RES)
    return sx0, sy0, sx1, sy1


def aoi_bbox_5070(aoi_path, margin_m):
    """AOI bounding box in EPSG:5070, grown by margin_m and grid-snapped.

    The corners of a lon/lat box do not map to the corners of the projected
    box, so all four are transformed and the envelope taken."""
    x0, y0, x1, y1 = aoi_bounds_4326(aoi_path)
    lons = [x0, x1, x0, x1, (x0 + x1) / 2, (x0 + x1) / 2]
    lats = [y0, y0, y1, y1, y0, y1]
    xs, ys = rio_transform("EPSG:4326", "EPSG:5070", lons, lats)
    return snap_bbox_5070(min(xs) - margin_m, min(ys) - margin_m,
                          max(xs) + margin_m, max(ys) + margin_m)


def fetch_nlcd(aoi_path, name, margin_m, out_dir, force=False):
    os.makedirs(out_dir, exist_ok=True)
    bx0, by0, bx1, by1 = aoi_bbox_5070(aoi_path, margin_m)
    _log(f"NLCD subset EPSG:5070 [{bx0:.0f} {by0:.0f} {bx1:.0f} {by1:.0f}] "
         f"= {(bx1-bx0)/1000:.0f} x {(by1-by0)/1000:.0f} km")
    out = {}
    for kind, coverage in NLCD_LAYERS.items():
        path = os.path.join(out_dir, f"nlcd2021_{kind}_{name}.tif")
        out[kind] = path
        if os.path.exists(path) and os.path.getsize(path) > 0 and not force:
            _log(f"  {os.path.basename(path)}: exists, kept")
            continue
        q = ("service=WCS&version=2.0.1&request=GetCoverage"
             f"&coverageId={coverage}&format=image/tiff"
             f"&subset=X({bx0:.0f},{bx1:.0f})&subset=Y({by0:.0f},{by1:.0f})")
        url = f"{WCS}?{q}"
        t0 = time.time()
        tmp = path + ".part"
        urllib.request.urlretrieve(url, tmp)
        with rasterio.open(tmp) as s:                 # fail loudly on an
            shape, crs = (s.height, s.width), str(s.crs)   # XML error body
        os.replace(tmp, path)
        rec = {"dataset": f"NLCD 2021 {kind} (L48)", "coverage_id": coverage,
               "url": url, "path": os.path.relpath(path, os.path.dirname(out_dir)),
               "bytes": os.path.getsize(path), "sha256": sha256(path),
               "shape": shape, "crs": crs,
               "bbox_5070": [bx0, by0, bx1, by1],
               "retrieved": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "seconds": round(time.time() - t0, 1),
               "license": "public domain (USGS/MRLC)"}
        manifest(out_dir, rec)
        _log(f"  {os.path.basename(path)}: {shape[1]}x{shape[0]} "
             f"({rec['bytes']/2**20:.0f} MB, {rec['seconds']:.0f}s)")
    return out


# ---------------------------------------------------------------- SSURGO ---
def wfs_tiles(x0, y0, x1, y1):
    """Split a lon/lat box into pieces under the WFS BBOX area limit."""
    import math
    mid_lat = (y0 + y1) / 2
    m_per_deg_lat = 111132.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(mid_lat))
    area = (x1 - x0) * m_per_deg_lon * (y1 - y0) * m_per_deg_lat
    n = max(1, math.ceil(math.sqrt(area / WFS_TILE_BUDGET_M2)))
    tiles = []
    for i in range(n):
        for j in range(n):
            tiles.append((x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * j / n,
                          x0 + (x1 - x0) * (i + 1) / n,
                          y0 + (y1 - y0) * (j + 1) / n))
    return tiles


def fetch_mapunits(aoi_path, name, margin_m, out_dir, force=False):
    """SSURGO map-unit polygons over the AOI, merged to one GeoJSON."""
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"ssurgo_mapunitpoly_{name}.geojson")
    if os.path.exists(out) and os.path.getsize(out) > 0 and not force:
        _log(f"  {os.path.basename(out)}: exists, kept")
        return out
    x0, y0, x1, y1 = aoi_bounds_4326(aoi_path)
    dlat = margin_m / 111132.0
    import math
    dlon = margin_m / (111320.0 * math.cos(math.radians((y0 + y1) / 2)))
    x0, y0, x1, y1 = x0 - dlon, y0 - dlat, x1 + dlon, y1 + dlat
    tiles = wfs_tiles(x0, y0, x1, y1)
    _log(f"SSURGO map units: {len(tiles)} WFS request(s) over "
         f"[{x0:.3f} {y0:.3f} {x1:.3f} {y1:.3f}]")

    seen, feats = set(), []
    scratch = out + ".d"
    os.makedirs(scratch, exist_ok=True)
    for i, (tx0, ty0, tx1, ty1) in enumerate(tiles):
        q = ("service=WFS&version=1.0.0&request=GetFeature"
             "&typename=mapunitpoly&srsName=EPSG:4326"
             f"&bbox={tx0:.6f},{ty0:.6f},{tx1:.6f},{ty1:.6f}")
        url = f"{SDA_WFS}?{q}"
        gml = os.path.join(scratch, f"t{i:03d}.gml")
        gj = os.path.join(scratch, f"t{i:03d}.json")
        t0 = time.time()
        urllib.request.urlretrieve(url, gml)
        head = open(gml, "rb").read(400)
        if b"ServiceException" in head:
            sys.exit(f"WFS error on tile {i}: {open(gml).read()[:500]}")
        for stale in (gj, gml.replace(".gml", ".gfs")):
            if os.path.exists(stale):
                os.remove(stale)
        subprocess.run([f"{GDAL}/ogr2ogr", "-f", "GeoJSON", gj, gml], check=True)
        got = json.load(open(gj))["features"]
        new = 0
        for f in got:
            k = f["properties"].get("mupolygonkey") or f["properties"].get("gml_id")
            if k in seen:
                continue
            seen.add(k)
            feats.append({"type": "Feature",
                          "properties": {"mukey": f["properties"]["mukey"],
                                         "musym": f["properties"].get("musym"),
                                         "areasymbol": f["properties"].get("areasymbol")},
                          "geometry": f["geometry"]})
            new += 1
        _log(f"  tile {i+1}/{len(tiles)}: {len(got):,} features, {new:,} new "
             f"({time.time()-t0:.0f}s)")
        manifest(out_dir, {"dataset": "SSURGO mapunitpoly (SDA WFS)",
                           "url": url, "features": len(got), "new": new,
                           "retrieved": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                           "license": "public domain (USDA-NRCS)"})
    feats.sort(key=lambda f: (f["properties"]["mukey"], json.dumps(
        f["geometry"]["coordinates"])[:64]))          # deterministic order
    with open(out, "w") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f)
    _log(f"-> {out} ({len(feats):,} polygons, "
         f"{len({f['properties']['mukey'] for f in feats}):,} map units)")
    for p in sorted(os.listdir(scratch)):
        os.remove(os.path.join(scratch, p))
    os.rmdir(scratch)
    return out


def sda_query(sql):
    body = json.dumps({"format": "JSON", "query": sql}).encode()
    req = urllib.request.Request(SDA_TABULAR, data=body,
                                 headers={"Content-Type": "application/json"})
    for attempt in range(4):
        try:
            return json.load(urllib.request.urlopen(req, timeout=180)).get("Table", [])
        except Exception as e:                       # SDA is occasionally flaky
            if attempt == 3:
                raise
            _log(f"  SDA retry {attempt+1}: {e}")
            time.sleep(5 * (attempt + 1))


def fetch_hydgrp(mapunit_path, name, out_dir, force=False):
    """component.hydgrp per mukey, aggregated by dominant component."""
    out = os.path.join(out_dir, f"ssurgo_hydgrp_{name}.json")
    if os.path.exists(out) and os.path.getsize(out) > 0 and not force:
        _log(f"  {os.path.basename(out)}: exists, kept")
        return out
    mukeys = sorted({f["properties"]["mukey"]
                     for f in json.load(open(mapunit_path))["features"]},
                    key=int)
    _log(f"SSURGO hydgrp: {len(mukeys):,} map units, "
         f"{-(-len(mukeys)//MUKEY_BATCH)} SDA query(ies)")
    rows = []
    for i in range(0, len(mukeys), MUKEY_BATCH):
        batch = mukeys[i:i + MUKEY_BATCH]
        sql = ("SELECT c.mukey, c.cokey, c.comppct_r, c.hydgrp, c.compname, "
               "c.majcompflag FROM component c WHERE c.mukey IN ("
               + ",".join(f"'{m}'" for m in batch) + ")")
        got = sda_query(sql) or []
        rows.extend(got)
        _log(f"  batch {i//MUKEY_BATCH+1}: {len(got):,} components")
    # dominant component: largest comppct_r with a hydgrp; ties -> lowest cokey
    best = {}
    for mukey, cokey, pct, hyd, compname, majc in rows:
        if not hyd:
            continue
        pct = int(pct) if pct not in (None, "") else 0
        key = (-pct, int(cokey))
        if mukey not in best or key < best[mukey][0]:
            best[mukey] = (key, {"hydgrp": hyd.strip(), "comppct_r": pct,
                                 "cokey": cokey, "compname": compname,
                                 "majcompflag": majc})
    table = {m: v[1] for m, v in sorted(best.items(), key=lambda kv: int(kv[0]))}
    missing = [m for m in mukeys if m not in table]
    doc = {"source": SDA_TABULAR,
           "rule": "dominant component: max comppct_r with a non-null hydgrp, "
                   "ties broken by lowest cokey",
           "retrieved": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "n_mapunits": len(mukeys), "n_with_hydgrp": len(table),
           "mapunits_without_hydgrp": missing,
           "hydgrp": table}
    with open(out, "w") as f:
        json.dump(doc, f, indent=1)
    from collections import Counter
    hist = Counter(v["hydgrp"] for v in table.values())
    _log(f"-> {out}: {len(table):,}/{len(mukeys):,} map units have a group "
         f"({len(missing):,} without) | " +
         " ".join(f"{k}:{v}" for k, v in sorted(hist.items())))
    manifest(out_dir, {"dataset": "SSURGO component.hydgrp (SDA tabular)",
                       "url": SDA_TABULAR, "n_mapunits": len(mukeys),
                       "n_with_hydgrp": len(table),
                       "retrieved": doc["retrieved"],
                       "license": "public domain (USDA-NRCS)"})
    return out


def main(aoi_path, name, margin_m=15000.0, force=False):
    margin_m = float(margin_m)
    root = data_root()
    lc_dir = os.path.join(root, "landcover")
    soil_dir = os.path.join(root, "soils")
    _log(f"data root: {root}")
    fetch_nlcd(aoi_path, name, margin_m, lc_dir, force)
    mu = fetch_mapunits(aoi_path, name, margin_m, soil_dir, force)
    fetch_hydgrp(mu, name, soil_dir, force)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--force"]
    main(*args[:3], force="--force" in sys.argv)
