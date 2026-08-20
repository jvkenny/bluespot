#!/usr/bin/env python3
"""Phase 1c — score the published Bluespot scenario depths against Chicago 311.

Question: when a real storm hits, do the places people report standing water
line up with the places the terrain model says water collects?

A hit rate on its own means nothing — drainage complaints cluster where people
live, and at 100 m tolerance a map that is 15% wet will "hit" almost anything.
So every event hit rate here is reported against three null models:

  street   random points along Chicago street centerlines
  uniform  random points uniformly inside the city boundary
  dryday   the SAME 311 complaint types on days with no measurable rain
           (the sharpest control: same reporting geography, no storm)

The deliverable is the RATIO, event / null, not the raw rate.

Water-on-street and water-in-basement are scored separately and never pooled:
the model represents surface ponding on terrain and represents nothing at all
about sewer surcharge into a basement.

Usage
  validate_311.py fetch          cache raw inputs to <data_root>/validation/
  validate_311.py score          compute results into data/derived/
  validate_311.py all            both (default)

Deterministic: all random sampling is seeded (SEED below); re-running from the
cache reproduces the JSON byte for byte.  Network pulls are cached and skipped
when the cache file already exists (--refresh forces a re-pull).
"""
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.warp import transform as warp_transform
from rasterio.windows import Window

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import data_root  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AOI = os.path.join(REPO, "data", "aoi", "chicago.geojson")
DERIVED = os.path.join(REPO, "data", "derived")

SEED = 20260819          # fixed: null-point sampling must be reproducible
# Everything is scored twice. 0.05 m is the product's own definition of "wet"
# and is the headline number. 0.30 m is added because 0.05 m SATURATES: a map
# that calls 10-19% of the city wet, tested with a 25 m tolerance, "hits" ~90%
# of random points, so it cannot discriminate anything. 0.30 m is roughly the
# depth at which ponding stops being cosmetic (and is the passability
# threshold Phase 2b plans to cite to FHWA/NWS vehicle-stall guidance).
DEPTH_LEVELS = (0.05, 0.30)
RADII_M = (0, 25, 50, 100)
N_NULL = 100000          # random points per geometric null model
CITY_GRID_M = 4          # resolution of the in-city rasterized mask
WINDOW_DAYS = 3          # event day + 2 days
UA = {"User-Agent": "bluespot-validation/1.0 (+https://github.com/jvkenny/bluespot)"}

# ---------------------------------------------------------------------------
# 311 service-request types. Discovered from the dataset itself (a group-by on
# sr_type over v6vf-nfxy, 2026-08-19); these are every SR_TYPE in the dataset
# that is plausibly a report of water where it should not be. Note the City's
# actual label is "Water ON Street", not "water in street".
# ---------------------------------------------------------------------------
SR_GROUPS = {
    # primary — what the terrain model actually claims to describe
    "street": ["Water On Street Complaint"],
    # primary — sewer surcharge, which the model does NOT represent
    "basement": ["Water in Basement Complaint"],
    # secondary — drainage-system complaints that spike with rain but describe
    # the pipe, not the puddle. Scored, reported, never pooled with the above.
    "sewer": [
        "Sewer Cleaning Inspection Request",
        "Sewer Cave-In Inspection Request",
        "Alley Sewer Inspection Request",
    ],
}
SR_ALL = [t for g in SR_GROUPS.values() for t in g]

# ---------------------------------------------------------------------------
# Storm events. Chosen 2026-08-19 from the 2019-2026 daily record at the two
# official NWS climate stations (see pick_events() docstring for the ranking
# that produced them). Rain totals are NOT hardcoded — they are fetched from
# ACIS at run time and written into the results.
# ---------------------------------------------------------------------------
EVENTS = [
    ("2023-07-02", "record storm; the wettest calendar day in the 311-era "
                   "record at Midway. Rain was far heavier on the West Side "
                   "and near-west suburbs than at either climate station."),
    ("2020-05-17", "second-wettest two-station day in the record; falls three "
                   "days after another 3.5 in event, so antecedent wetness is "
                   "unusually high."),
    ("2026-07-27", "mid-size summer convective event."),
    ("2026-08-01", "largest August 2026 event."),
    ("2026-08-09", "second August 2026 event; the small end of the range."),
]

# Bookmarks published in <data_root>/citywide/. rain_in None = static envelope.
SCENARIOS = [
    ("r10",       1.00, "chicago_depth_r10.tif"),
    ("b75_2yr",   3.34, "chicago_depth_b75_2yr.tif"),
    ("b70_100yr", 7.58, "chicago_depth_b70_100yr.tif"),
    ("b75_100yr", 8.57, "chicago_depth_b75_100yr.tif"),
    ("full",      None, "chicago_depth_cog.tif"),
]

# NWS ASOS climate stations. ACIS station ids (Midway has no usable GHCN id in
# ACIS; its call-sign id resolves correctly and is what xmACIS2 uses).
STATIONS = [("ORD", "Chicago O'Hare Intl AP"), ("MDW", "Chicago Midway AP")]
ACIS_START = "2019-01-01"
DRY_MAX_IN = 0.10        # a "dry day" has < this at BOTH stations...
DRY_LOOKBACK = 2         # ...and on the previous this-many days too


def vdir():
    d = os.path.join(data_root(), "validation")
    os.makedirs(d, exist_ok=True)
    return d


def log(*a):
    print(*a, flush=True)


# ===========================================================================
# fetch
# ===========================================================================
def _get(url, tries=5):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                        timeout=300) as r:
                return r.read()
        except Exception as e:            # noqa: BLE001 - transient portal errors
            last = e
            log("   retry %d: %s" % (i + 1, e))
            time.sleep(3 * (i + 1))
    raise RuntimeError("GET failed: %s (%s)" % (url, last))


def _post_json(url, body, tries=5):
    data = json.dumps(body).encode()
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(
                url, data=data,
                headers=dict(UA, **{"Content-Type": "application/json"}))
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.load(r)
        except Exception as e:            # noqa: BLE001
            last = e
            log("   retry %d: %s" % (i + 1, e))
            time.sleep(3 * (i + 1))
    raise RuntimeError("POST failed: %s (%s)" % (url, last))


def fetch_311(refresh=False):
    """All flood-related SRs with a geocode, paged out of Socrata to NDJSON."""
    out = os.path.join(vdir(), "sr_flood.ndjson")
    if os.path.exists(out) and not refresh:
        log("311: cached", out)
        return out
    where = "sr_type in (%s) AND latitude IS NOT NULL" % \
            ",".join("'%s'" % t.replace("'", "''") for t in SR_ALL)
    page, off, n = 50000, 0, 0
    tmp = out + ".part"
    with open(tmp, "w") as fh:
        while True:
            url = "https://data.cityofchicago.org/resource/v6vf-nfxy.json?" + \
                urllib.parse.urlencode({
                    "$select": "sr_number,sr_type,created_date,latitude,"
                               "longitude,duplicate",
                    "$where": where,
                    "$order": ":id",
                    "$limit": str(page),
                    "$offset": str(off),
                })
            rows = json.loads(_get(url))
            for r in rows:
                fh.write(json.dumps(r, sort_keys=True) + "\n")
            n += len(rows)
            log("   311 rows %d" % n)
            if len(rows) < page:
                break
            off += page
    os.replace(tmp, out)
    log("311: wrote %d rows -> %s" % (n, out))
    return out


def fetch_acis(refresh=False):
    """Daily precipitation at the two official NWS climate stations (ACIS)."""
    out = os.path.join(vdir(), "acis_daily.json")
    if os.path.exists(out) and not refresh:
        log("acis: cached", out)
        return out
    end = max(e[0] for e in EVENTS)
    res = {"retrieved": time.strftime("%Y-%m-%d"), "stations": {}}
    for sid, name in STATIONS:
        r = _post_json("https://data.rcc-acis.org/StnData", {
            "sid": sid, "sdate": ACIS_START, "edate": end,
            "elems": [{"name": "pcpn", "interval": "dly", "prec": 2}],
            "meta": "name,ll,sids"})
        res["stations"][sid] = {"meta": r["meta"],
                                "data": {d: v for d, v in r["data"]}}
        log("   acis %s: %d days" % (sid, len(r["data"])))
        time.sleep(1)
    with open(out, "w") as fh:
        json.dump(res, fh, indent=1, sort_keys=True)
    return out


def fetch_acis_spread(refresh=False):
    """Every ACIS station in the Chicago bbox on each event day.

    Only used to quantify how much the storm total varied ACROSS the city; the
    headline event total stays the two-station mean.
    """
    out = os.path.join(vdir(), "acis_event_spread.json")
    if os.path.exists(out) and not refresh:
        log("acis-spread: cached", out)
        return out
    res = {"retrieved": time.strftime("%Y-%m-%d"),
           "bbox": "-87.95,41.63,-87.50,42.05", "events": {}}
    for day, _ in EVENTS:
        r = _post_json("https://data.rcc-acis.org/MultiStnData", {
            "bbox": res["bbox"], "sdate": day, "edate": day,
            "elems": "pcpn",          # string form: full precision (dict form rounds)
            "meta": "name,ll"})
        res["events"][day] = [
            {"name": s["meta"]["name"], "ll": s["meta"].get("ll"),
             "pcpn": s["data"][0]} for s in r.get("data", [])]
        log("   acis-spread %s: %d stations" % (day, len(res["events"][day])))
        time.sleep(1)
    with open(out, "w") as fh:
        json.dump(res, fh, indent=1, sort_keys=True)
    return out


def fetch_streets(refresh=False):
    out = os.path.join(vdir(), "street_center_lines.geojson")
    if os.path.exists(out) and not refresh:
        log("streets: cached", out)
        return out
    url = ("https://data.cityofchicago.org/api/geospatial/pr57-gg9e"
           "?method=export&format=GeoJSON")
    tmp = out + ".part"
    with open(tmp, "wb") as fh:
        fh.write(_get(url))
    os.replace(tmp, out)
    log("streets: wrote", out)
    return out


def cmd_fetch(refresh=False):
    fetch_311(refresh)
    fetch_acis(refresh)
    fetch_acis_spread(refresh)
    fetch_streets(refresh)


# ===========================================================================
# rainfall bookkeeping
# ===========================================================================
def _in(v):
    """ACIS daily value -> inches. 'T' (trace) = 0. 'M'/'S' (missing) = None."""
    if v in ("M", "S", None, ""):
        return None
    if v == "T":
        return 0.0
    try:
        return float(v)
    except ValueError:
        return None


def load_rain():
    d = json.load(open(os.path.join(vdir(), "acis_daily.json")))
    per = {sid: {k: _in(v) for k, v in s["data"].items()}
           for sid, s in d["stations"].items()}
    return d, per


def event_total(per, day):
    """Event rain total = mean of the two official NWS climate stations.

    Stated simplification: the scenario model applies ONE rain depth to the
    whole city, so the observation it is scored against must also be one
    number. Per-station values and the citywide station spread are reported
    alongside so the reader can see how much that simplification costs.
    """
    vals = {sid: per[sid].get(day) for sid, _ in STATIONS}
    good = [v for v in vals.values() if v is not None]
    return (sum(good) / len(good) if good else None), vals


def dry_days(per):
    """Days with < DRY_MAX_IN at both stations, on the day and the 2 before."""
    import datetime as dt
    days = sorted(set().union(*[set(v) for v in per.values()]))
    ok = []
    for day in days:
        d0 = dt.date.fromisoformat(day)
        good = True
        for back in range(DRY_LOOKBACK + 1):
            k = (d0 - dt.timedelta(days=back)).isoformat()
            vs = [per[sid].get(k) for sid, _ in STATIONS]
            if any(v is None for v in vs) or max(vs) >= DRY_MAX_IN:
                good = False
                break
        if good:
            ok.append(day)
    return set(ok)


def window_days(day):
    import datetime as dt
    d0 = dt.date.fromisoformat(day)
    return {(d0 + dt.timedelta(days=i)).isoformat() for i in range(WINDOW_DAYS)}


# ===========================================================================
# geometry / point sets
# ===========================================================================
def load_city_geoms():
    gj = json.load(open(AOI))
    geoms = [f["geometry"] for f in gj["features"]]
    return [g for g in warp_transform_geoms(geoms)]


def warp_transform_geoms(geoms):
    from rasterio.warp import transform_geom
    return [transform_geom("EPSG:4326", "EPSG:26916", g) for g in geoms]


def city_grid(ref_profile):
    """Boolean in-city mask at CITY_GRID_M, aligned to the depth raster grid."""
    t = ref_profile["transform"]
    k = CITY_GRID_M
    w = int(math.ceil(ref_profile["width"] / k))
    h = int(math.ceil(ref_profile["height"] / k))
    tr = rasterio.Affine(t.a * k, t.b, t.c, t.d, t.e * k, t.f)
    arr = rasterize(((g, 1) for g in load_city_geoms()), out_shape=(h, w),
                    transform=tr, fill=0, dtype="uint8").astype(bool)
    return arr, tr


def to_rowcol(lon, lat, profile):
    """lon/lat arrays -> integer (row, col) on the depth raster grid."""
    x, y = warp_transform("EPSG:4326", "EPSG:26916",
                          list(np.asarray(lon, float)),
                          list(np.asarray(lat, float)))
    t = profile["transform"]
    col = np.floor((np.asarray(x) - t.c) / t.a).astype(np.int64)
    row = np.floor((np.asarray(y) - t.f) / t.e).astype(np.int64)
    return row, col


def sample_uniform(cityarr, citytr, profile, n, rng):
    """Random points uniform over the city polygon's area."""
    idx = np.flatnonzero(cityarr.ravel())
    pick = rng.choice(idx, size=n, replace=True)
    gr, gc = np.divmod(pick, cityarr.shape[1])
    x = citytr.c + (gc + rng.random(n)) * citytr.a
    y = citytr.f + (gr + rng.random(n)) * citytr.e
    t = profile["transform"]
    return (np.floor((y - t.f) / t.e).astype(np.int64),
            np.floor((x - t.c) / t.a).astype(np.int64))


def sample_streets(profile, n, rng):
    """Random points along city street centerlines, weighted by length.

    Street classes 1-4 (expressway, arterial, collector, local) with status
    'N' (in service). Expressways are kept deliberately: excluding them would
    strip the deepest pools in the city out of the null and flatter the model.
    """
    gj = json.load(open(os.path.join(vdir(), "street_center_lines.geojson")))
    segs_x, segs_y = [], []
    kept = 0
    for f in gj["features"]:
        p = f.get("properties") or {}
        if p.get("class") not in ("1", "2", "3", "4") or p.get("status") != "N":
            continue
        g = f.get("geometry")
        if not g:
            continue
        parts = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
        for line in parts:
            if len(line) < 2:
                continue
            kept += 1
            a = np.asarray(line, float)
            segs_x.append(a[:, 0])
            segs_y.append(a[:, 1])
    lon = np.concatenate(segs_x)
    lat = np.concatenate(segs_y)
    X, Y = warp_transform("EPSG:4326", "EPSG:26916", list(lon), list(lat))
    X = np.asarray(X)
    Y = np.asarray(Y)
    # rebuild per-line vertex ranges, then per-segment endpoints
    starts, off = [], 0
    for sx in segs_x:
        starts.append((off, off + len(sx)))
        off += len(sx)
    i0 = np.concatenate([np.arange(a, b - 1) for a, b in starts])
    i1 = i0 + 1
    x0, y0, x1, y1 = X[i0], Y[i0], X[i1], Y[i1]
    ln = np.hypot(x1 - x0, y1 - y0)
    keep = ln > 0
    x0, y0, x1, y1, ln = x0[keep], y0[keep], x1[keep], y1[keep], ln[keep]
    cum = np.cumsum(ln)
    pos = rng.random(n) * cum[-1]
    j = np.searchsorted(cum, pos)
    f = rng.random(n)
    x = x0[j] + (x1[j] - x0[j]) * f
    y = y0[j] + (y1[j] - y0[j]) * f
    t = profile["transform"]
    log("   streets: %d line parts, %.0f km of centerline" % (kept, cum[-1] / 1000.0))
    return (np.floor((y - t.f) / t.e).astype(np.int64),
            np.floor((x - t.c) / t.a).astype(np.int64)), cum[-1]


# ===========================================================================
# raster masks + proximity test
# ===========================================================================
def build_mask(path, pad, level):
    """Boolean 'ponded' mask (depth >= level m), padded by `pad` cells.

    NaN (open water / outside the city) compares False, i.e. counts as dry.
    """
    with rasterio.open(path) as ds:
        H, W = ds.height, ds.width
        m = np.zeros((H + 2 * pad, W + 2 * pad), dtype=bool)
        step = 4096
        for r0 in range(0, H, step):
            h = min(step, H - r0)
            a = ds.read(1, window=Window(0, r0, W, h))
            with np.errstate(invalid="ignore"):
                m[pad + r0:pad + r0 + h, pad:pad + W] = a >= level
    return m


def _disk(r):
    if r == 0:
        return np.ones((1, 1), bool)
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return (x * x + y * y) <= r * r


def first_hit_radius(mask, rows, cols, pad, radii=RADII_M):
    """Index into `radii` of the smallest radius with a ponded cell, else -1.

    Points are unique (row, col) pairs already inside the raster.
    """
    n = len(rows)
    out = np.full(n, -1, np.int8)
    r0 = rows + pad
    c0 = cols + pad
    # radius 0 is a plain gather
    hit0 = mask[r0, c0]
    out[hit0] = 0
    todo = np.flatnonzero(~hit0)
    for i, R in enumerate(radii[1:], start=1):
        if todo.size == 0:
            break
        d = _disk(R)
        still = []
        for j in todo:
            r, c = r0[j], c0[j]
            if (mask[r - R:r + R + 1, c - R:c + R + 1] & d).any():
                out[j] = i
            else:
                still.append(j)
        todo = np.asarray(still, dtype=np.int64)
        log("      r=%3dm: %d of %d located, %d still dry"
            % (R, n - todo.size, n, todo.size))
    return out


# ===========================================================================
# statistics
# ===========================================================================
def wilson(k, n, z=1.959963984540054):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def two_prop_z(k1, n1, k2, n2):
    """z and two-sided p for H0: p1 == p2 (normal approximation)."""
    if n1 == 0 or n2 == 0:
        return None, None
    p1, p2 = k1 / n1, k2 / n2
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return None, None
    z = (p1 - p2) / se
    return z, math.erfc(abs(z) / math.sqrt(2))


# ===========================================================================
# score
# ===========================================================================
def cmd_score():
    os.makedirs(DERIVED, exist_ok=True)
    cw = os.path.join(data_root(), "citywide")
    ref_path = os.path.join(cw, SCENARIOS[0][2])
    with rasterio.open(ref_path) as ds:
        profile = {"transform": ds.transform, "width": ds.width,
                   "height": ds.height, "crs": str(ds.crs)}
    log("reference grid: %dx%d %s" % (profile["width"], profile["height"],
                                      profile["crs"]))

    acis_meta, per = load_rain()
    dry = dry_days(per)
    log("dry days available: %d" % len(dry))

    # ---- 311 point sets -------------------------------------------------
    log("loading 311 ...")
    recs = {g: {"day": [], "lat": [], "lon": [], "dup": []} for g in SR_GROUPS}
    type2group = {t: g for g, ts in SR_GROUPS.items() for t in ts}
    ntot = 0
    with open(os.path.join(vdir(), "sr_flood.ndjson")) as fh:
        for line in fh:
            r = json.loads(line)
            g = type2group.get(r["sr_type"])
            if g is None:
                continue
            try:
                lat = float(r["latitude"])
                lon = float(r["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            recs[g]["day"].append(r["created_date"][:10])
            recs[g]["lat"].append(lat)
            recs[g]["lon"].append(lon)
            recs[g]["dup"].append(bool(r.get("duplicate")))
            ntot += 1
    log("311 geocoded rows: %d" % ntot)
    for g in recs:
        for k in recs[g]:
            recs[g][k] = np.asarray(recs[g][k])
        log("   %-9s %d" % (g, len(recs[g]["day"])))

    # ---- build every point set we will score ----------------------------
    rng = np.random.default_rng(SEED)
    cityarr, citytr = city_grid(profile)
    log("in-city cells at %dm: %d (%.1f km2)" %
        (CITY_GRID_M, cityarr.sum(), cityarr.sum() * CITY_GRID_M ** 2 / 1e6))

    psets = {}     # name -> (rows, cols) raw, pre-filter
    meta = {}

    for g in SR_GROUPS:
        r, c = to_rowcol(recs[g]["lon"], recs[g]["lat"], profile)
        recs[g]["row"], recs[g]["col"] = r, c
        for day, _ in EVENTS:
            w = window_days(day)
            sel = np.isin(recs[g]["day"], list(w))
            psets["ev|%s|%s" % (day, g)] = (r[sel], c[sel])
            meta["ev|%s|%s" % (day, g)] = {
                "n_records": int(sel.sum()),
                "n_duplicate_flagged": int(recs[g]["dup"][sel].sum())}
        seld = np.isin(recs[g]["day"], list(dry))
        psets["dryday|%s" % g] = (r[seld], c[seld])
        meta["dryday|%s" % g] = {"n_records": int(seld.sum())}

    ur, uc = sample_uniform(cityarr, citytr, profile, N_NULL, rng)
    psets["null|uniform"] = (ur, uc)
    (sr_, sc_), street_km = sample_streets(profile, N_NULL, rng)
    psets["null|street"] = (sr_, sc_)
    meta["null|street"] = {"centerline_km": street_km / 1000.0}

    # ---- filter to the raster, and to the city ---------------------------
    H, W = profile["height"], profile["width"]
    valid = {}
    for k, (r, c) in psets.items():
        inb = (r >= 0) & (r < H) & (c >= 0) & (c < W)
        gr = np.clip(r // CITY_GRID_M, 0, cityarr.shape[0] - 1)
        gc = np.clip(c // CITY_GRID_M, 0, cityarr.shape[1] - 1)
        incity = inb & cityarr[gr, gc]
        valid[k] = incity
        meta.setdefault(k, {})
        meta[k]["n_points"] = int(len(r))
        meta[k]["n_outside_raster"] = int((~inb).sum())
        meta[k]["n_outside_city"] = int((inb & ~incity).sum())
        meta[k]["n_scored"] = int(incity.sum())

    # global unique (row,col) so each location is tested once per scenario
    allr = np.concatenate([psets[k][0][valid[k]] for k in psets])
    allc = np.concatenate([psets[k][1][valid[k]] for k in psets])
    key = allr.astype(np.int64) * (W + 1) + allc.astype(np.int64)
    uniq, inv = np.unique(key, return_inverse=True)
    ur_ = (uniq // (W + 1)).astype(np.int64)
    uc_ = (uniq % (W + 1)).astype(np.int64)
    log("unique locations to test: %d (from %d points)" % (len(uniq), len(allr)))

    # index slices back into each point set
    slices, off = {}, 0
    for k in psets:
        n = int(valid[k].sum())
        slices[k] = inv[off:off + n]
        off += n

    # ---- score every scenario -------------------------------------------
    pad = max(RADII_M)
    results = {}
    for sid, rain_in, fn in SCENARIOS:
        path = os.path.join(cw, fn)
        results[sid] = {"rain_in": rain_in, "file": fn, "levels": {}}
        for level in DEPTH_LEVELS:
            t0 = time.time()
            log("scenario %s (%s) at >=%.2f m ..." % (sid, fn, level))
            mask = build_mask(path, pad, level)
            wet = int(mask.sum())
            log("   mask built in %.1fs, wet cells %d" % (time.time() - t0, wet))
            fh = first_hit_radius(mask, ur_, uc_, pad)
            del mask
            log("   scored %d unique locations in %.1fs"
                % (len(uniq), time.time() - t0))
            per_set = {}
            for k in psets:
                f = fh[slices[k]]
                n = len(f)
                row = {"n": n}
                for i, R in enumerate(RADII_M):
                    k_ = int(((f >= 0) & (f <= i)).sum())
                    lo, hi = wilson(k_, n)
                    row["r%d" % R] = {"hits": k_, "rate": (k_ / n) if n else None,
                                      "ci95": [lo, hi]}
                per_set[k] = row
            results[sid]["levels"]["%.2f" % level] = {
                "wet_cells": wet, "sets": per_set}

    # ---- assemble the report --------------------------------------------
    spread = json.load(open(os.path.join(vdir(), "acis_event_spread.json")))
    events_out = []
    for day, why in EVENTS:
        tot, vals = event_total(per, day)
        near = min([s for s in SCENARIOS if s[1] is not None],
                   key=lambda s: abs(s[1] - tot))
        sp = [_in(s["pcpn"]) for s in spread["events"].get(day, [])]
        sp = sorted(v for v in sp if v is not None)
        events_out.append({
            "date": day, "why": why,
            "station_in": vals,
            "event_total_in": round(tot, 2),
            "nearest_bookmark": near[0],
            "nearest_bookmark_in": near[1],
            "window": sorted(window_days(day)),
            "city_station_spread": {
                "n": len(sp),
                "min": sp[0] if sp else None,
                "median": sp[len(sp) // 2] if sp else None,
                "max": sp[-1] if sp else None},
        })

    out = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "seed": SEED,
        "depth_levels_m": list(DEPTH_LEVELS),
        "city_area_km2": float(cityarr.sum()) * CITY_GRID_M ** 2 / 1e6,
        "radii_m": list(RADII_M),
        "window_days": WINDOW_DAYS,
        "n_null_points": N_NULL,
        "dry_day_rule": {"max_in": DRY_MAX_IN, "lookback_days": DRY_LOOKBACK,
                         "n_dry_days": len(dry)},
        "sr_groups": SR_GROUPS,
        "acis_retrieved": acis_meta["retrieved"],
        "events": events_out,
        "point_sets": meta,
        "scenarios": results,
    }
    p = os.path.join(DERIVED, "validation_311.json")
    with open(p, "w") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    log("wrote", p)
    write_tables(out)
    return out


GROUP_LABELS = (
    ("street", "Water On Street Complaint"),
    ("basement", "Water in Basement Complaint"),
    ("sewer", "Sewer-related requests"),
)
NULLS = (("street network", "null|street"),
         ("uniform in city", "null|uniform"),
         ("same type, dry days", "dryday|%s"))


def _lvl(out, sid, level):
    return out["scenarios"][sid]["levels"]["%.2f" % level]["sets"]


def _pct(row, radii):
    return " | ".join("%.1f%%" % (100 * row["r%d" % R]["rate"]) for R in radii)


def write_tables(out):
    """Markdown tables — the numeric body of docs/VALIDATION.md."""
    L = []
    A = L.append
    R = out["radii_m"]
    levels = out["depth_levels_m"]
    ndry = out["dry_day_rule"]["n_dry_days"]
    wdays = out["window_days"]
    city_km2 = out["city_area_km2"]

    A("<!-- generated by pipeline/validate_311.py — do not hand-edit -->")
    A("")
    A("## 1. Events scored")
    A("")
    A("| event | O'Hare in | Midway in | event total in | citywide gauges (n, min / median / max) | nearest bookmark |")
    A("|---|---|---|---|---|---|")
    for e in out["events"]:
        s = e["city_station_spread"]
        A("| %s | %s | %s | **%.2f** | %d, %.2f / %.2f / %.2f | %s (%.2f in) |" % (
            e["date"], e["station_in"]["ORD"], e["station_in"]["MDW"],
            e["event_total_in"], s["n"], s["min"], s["median"], s["max"],
            e["nearest_bookmark"], e["nearest_bookmark_in"]))
    A("")
    A("Event total = mean of the two official NWS climate stations. The gauge")
    A("column is every ACIS station in the Chicago bounding box that reported")
    A("that day (ASOS + COOP + CoCoRaHS, mixed observation windows) and is")
    A("there to show how much a single citywide number hides.")
    A("")

    A("## 2. Complaint volume — the temporal signal")
    A("")
    A("Complaints per day in each event window (event day + %d days) against"
      % (wdays - 1))
    A("the dry-day rate over %d qualifying dry days." % ndry)
    A("")
    A("| event | water on street /day | x dry | water in basement /day | x dry | sewer /day | x dry |")
    A("|---|---|---|---|---|---|---|")
    base = {g: out["point_sets"]["dryday|%s" % g]["n_scored"] / ndry
            for g, _ in GROUP_LABELS}
    for e in out["events"]:
        cells = []
        for g, _ in GROUP_LABELS:
            r = out["point_sets"]["ev|%s|%s" % (e["date"], g)]["n_scored"] / wdays
            cells.append("%.0f | **%.0fx**" % (r, r / base[g]))
        A("| %s | %s |" % (e["date"], " | ".join(cells)))
    A("| *dry-day baseline* | %.1f | 1x | %.1f | 1x | %.1f | 1x |"
      % tuple(base[g] for g, _ in GROUP_LABELS))
    A("")

    A("## 3. How much of the city each map covers")
    A("")
    A("The reason tolerance radii saturate. \"Reachable\" = share of a uniform")
    A("random sample of the city within that radius of a ponded cell.")
    A("")
    A("| bookmark | depth | wet km2 | % of city | reachable @25 m | @50 m | @100 m |")
    A("|---|---|---|---|---|---|---|")
    for sid in out["scenarios"]:
        for lv in levels:
            w = out["scenarios"][sid]["levels"]["%.2f" % lv]["wet_cells"] / 1e6
            u = _lvl(out, sid, lv)["null|uniform"]
            A("| %s | >=%.2f m | %.1f | %.1f%% | %s |" % (
                sid, lv, w, 100 * w / city_km2,
                " | ".join("%.1f%%" % (100 * u["r%d" % r]["rate"])
                           for r in R[1:])))
    A("")

    for lv in levels:
        A("## 4. Hit rates at ponded depth >= %.2f m" % lv)
        A("")
        for g, gl in GROUP_LABELS:
            A("### %s" % gl)
            A("")
            A("| point set | bookmark | n | " + " | ".join("%d m" % r for r in R) + " |")
            A("|---|---|---|" + "---|" * len(R))
            for e in out["events"]:
                sid = e["nearest_bookmark"]
                row = _lvl(out, sid, lv)["ev|%s|%s" % (e["date"], g)]
                A("| %s | %s | %d | %s |" % (e["date"], sid, row["n"],
                                             _pct(row, R)))
            for nm, key in NULLS:
                k = key % g if "%s" in key else key
                for sid in ("r10", "b75_2yr"):
                    row = _lvl(out, sid, lv)[k]
                    A("| *null: %s* | %s | %d | %s |" % (nm, sid, row["n"],
                                                         _pct(row, R)))
            A("")

        A("### Skill at >=%.2f m — event rate / null rate" % lv)
        A("")
        for g, gl in GROUP_LABELS:
            A("**%s**" % gl)
            A("")
            A("| event | null | " + " | ".join("ratio @%d m" % r for r in R) +
              " | z @0 m | z @25 m | p @25 m |")
            A("|---|---|" + "---|" * (len(R) + 3))
            for e in out["events"]:
                sid = e["nearest_bookmark"]
                ev = _lvl(out, sid, lv)["ev|%s|%s" % (e["date"], g)]
                for nm, key in NULLS:
                    k = key % g if "%s" in key else key
                    nu = _lvl(out, sid, lv)[k]
                    ratios = []
                    for r in R:
                        a, b = ev["r%d" % r]["rate"], nu["r%d" % r]["rate"]
                        ratios.append("%.2f" % (a / b) if b else "—")
                    z0, _ = two_prop_z(ev["r0"]["hits"], ev["n"],
                                       nu["r0"]["hits"], nu["n"])
                    z25, p25 = two_prop_z(ev["r25"]["hits"], ev["n"],
                                          nu["r25"]["hits"], nu["n"])
                    A("| %s | %s | %s | %s | %s | %s |" % (
                        e["date"], nm.split(",")[0], " | ".join(ratios),
                        "%+.1f" % z0 if z0 is not None else "—",
                        "%+.1f" % z25 if z25 is not None else "—",
                        ("%.1e" % p25) if p25 is not None else "—"))
            A("")

        A("### Pooled across all five storms, >=%.2f m" % lv)
        A("")
        A("Each event's complaints are scored against ITS OWN nearest bookmark,")
        A("then pooled. Expected = sum over events of n_event x null rate at")
        A("that event's bookmark; z is the normal approximation to the")
        A("Poisson-binomial. Spatial clustering is NOT accounted for, so treat")
        A("these p-values as an upper bound on confidence.")
        A("")
        A("| complaint type | null | radius | observed | expected | ratio | z | p |")
        A("|---|---|---|---|---|---|---|---|")
        for g, gl in GROUP_LABELS:
            for nm, key in NULLS:
                k = key % g if "%s" in key else key
                for r in R:
                    obs = exp = var = ntot = 0
                    for e in out["events"]:
                        sid = e["nearest_bookmark"]
                        ev = _lvl(out, sid, lv)["ev|%s|%s" % (e["date"], g)]
                        pn = _lvl(out, sid, lv)[k]["r%d" % r]["rate"]
                        obs += ev["r%d" % r]["hits"]
                        ntot += ev["n"]
                        exp += ev["n"] * pn
                        var += ev["n"] * pn * (1 - pn)
                    if var <= 0 or ntot == 0:
                        continue
                    z = (obs - exp) / math.sqrt(var)
                    pv = math.erfc(abs(z) / math.sqrt(2))
                    A("| %s | %s | %d m | %d / %d (%.1f%%) | %.0f (%.1f%%) | "
                      "**%.2f** | %+.1f | %.1e |" % (
                          gl, nm.split(",")[0], r, obs, ntot,
                          100.0 * obs / ntot, exp, 100.0 * exp / ntot,
                          obs / exp if exp else float("nan"), z, pv))
        A("")

    A("## 5. Appendix — every bookmark, every point set")
    A("")
    A("Hit rate at 25 m tolerance. `full` is the static max-fill envelope, not")
    A("a rain scenario.")
    A("")
    keys = ([("ev|%s|%s" % (e["date"], g)) for g, _ in GROUP_LABELS
             for e in out["events"]] +
            ["dryday|%s" % g for g, _ in GROUP_LABELS] +
            ["null|street", "null|uniform"])
    for lv in levels:
        A("**ponded depth >= %.2f m**" % lv)
        A("")
        A("| point set | " + " | ".join(out["scenarios"]) + " |")
        A("|---" * (len(out["scenarios"]) + 1) + "|")
        for k in keys:
            A("| `%s` | %s |" % (k, " | ".join(
                "%.1f%%" % (100 * _lvl(out, s, lv)[k]["r25"]["rate"])
                for s in out["scenarios"])))
        A("")

    A("## 6. Point-set bookkeeping")
    A("")
    A("| point set | points | outside raster | outside city | scored |")
    A("|---|---|---|---|---|")
    for k in keys:
        m = out["point_sets"][k]
        A("| `%s` | %d | %d | %d | %d |" % (
            k, m["n_points"], m["n_outside_raster"], m["n_outside_city"],
            m["n_scored"]))
    A("")

    p = os.path.join(DERIVED, "validation_311_tables.md")
    with open(p, "w") as fh:
        fh.write("\n".join(L) + "\n")
    log("wrote", p)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    refresh = "--refresh" in sys.argv
    cmd = args[0] if args else "all"
    if cmd in ("fetch", "all"):
        cmd_fetch(refresh)
    if cmd in ("score", "all"):
        cmd_score()


if __name__ == "__main__":
    main()
