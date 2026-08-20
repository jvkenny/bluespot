#!/usr/bin/env python3
"""Shared helpers for the lifeline-places fetchers (Phase 2a).

Lifeline places are PUBLIC PLACES people depend on in a storm — schools, fire
and police stations, hospitals, pharmacies, groceries, substations, water and
wastewater plants. This module only knows how to fetch, clip, standardise and
deduplicate points. It says nothing about the condition, value or management
of anything; see AGENTS.md.

Standard output schema, one GeoJSON FeatureCollection per category, EPSG:4326,
Point geometry only:

    name       str        human-readable place name ("" when the source has none)
    category   str        one of CATEGORIES
    source     str        short source key, resolvable in data/SOURCES.md
    source_id  str        stable id within that source (portal row id, OSM
                          type/id, CMS facility id, ...)
    retrieved  str        ISO date the source was pulled
    subtype    str|None   place kind within the category, verbatim from the
                          source where one exists (e.g. hospital
                          "with_emergency_department", school "HS",
                          shop "supermarket"). Optional sixth property; the
                          five above are always present.
"""
import json, math, os, sys, time, urllib.parse, urllib.request

CATEGORIES = [
    "schools",
    "fire_stations",
    "police_stations",
    "hospitals",
    "pharmacies",
    "grocery",
    "substations",
    "water_wastewater",
]

UA = "bluespot-pipeline/0.1 (https://github.com/jvkenny/bluespot)"

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.osm.jp/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AOI = os.path.join(REPO, "data", "aoi", "chicago.geojson")
OUT_DIR = os.path.join(REPO, "data", "lifelines")


# ---------------------------------------------------------------- http

def get_json(url, timeout=120, tries=5):
    """GET a JSON document with backoff. stdlib only, per repo convention."""
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception as ex:                       # noqa: BLE001
            last = ex
            print(f"  GET failed ({ex}); retry {attempt + 1}/{tries}")
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed: {last}")


def overpass(query, timeout=300, tries=10, polite_s=3):
    """POST an Overpass QL query, rotating mirrors. Returns elements list.

    Overpass is a free service run by volunteers: one query per call, backoff
    on failure, and never hammer a single mirror.
    """
    last = None
    for attempt in range(tries):
        ep = OVERPASS_ENDPOINTS[attempt % len(OVERPASS_ENDPOINTS)]
        try:
            req = urllib.request.Request(
                ep, data=query.encode(), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout + 60) as r:
                els = json.load(r)["elements"]
            time.sleep(polite_s)
            return els
        except Exception as ex:                       # noqa: BLE001
            last = ex
            print(f"  {ep}: {ex}; retrying...")
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"Overpass failed on all mirrors: {last}")


# ---------------------------------------------------------------- geometry

def _rings(aoi_path=AOI):
    """AOI polygons as [(outer, [holes...]), ...] in EPSG:4326."""
    gj = json.load(open(aoi_path))
    polys = []
    for f in gj["features"]:
        g = f["geometry"]
        parts = ([g["coordinates"]] if g["type"] == "Polygon"
                 else g["coordinates"])
        for p in parts:
            polys.append((p[0], p[1:]))
    return polys


def _in_ring(ring, x, y):
    inside = False
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i][0], ring[i][1]
        x1, y1 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y0 > y) != (y1 > y):
            xi = x0 + (y - y0) / (y1 - y0) * (x1 - x0)
            if x < xi:
                inside = not inside
    return inside


class Clip:
    """Point-in-AOI test with a bbox prefilter and hole handling."""

    def __init__(self, aoi_path=AOI):
        self.polys = _rings(aoi_path)
        self.boxes = []
        for outer, _ in self.polys:
            xs = [c[0] for c in outer]
            ys = [c[1] for c in outer]
            self.boxes.append((min(xs), min(ys), max(xs), max(ys)))

    def contains(self, x, y):
        for (outer, holes), (x0, y0, x1, y1) in zip(self.polys, self.boxes):
            if not (x0 <= x <= x1 and y0 <= y <= y1):
                continue
            if _in_ring(outer, x, y) and not any(
                    _in_ring(h, x, y) for h in holes):
                return True
        return False


def centroid(coords):
    """Mean of a coordinate list. OSM ways/relations are reduced to a point;
    a lifeline place is a location to reach, not an outline."""
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def metres_apart(a, b):
    """Rough planar distance in metres; fine at Chicago's latitude for the
    ~100 m dedupe radius."""
    mx = 111_320.0 * math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot((a[0] - b[0]) * mx, (a[1] - b[1]) * 110_540.0)


# ---------------------------------------------------------------- records

def feature(name, category, source, source_id, retrieved, lon, lat,
            subtype=None):
    return {
        "type": "Feature",
        "properties": {
            "name": (name or "").strip(),
            "category": category,
            "source": source,
            "source_id": str(source_id),
            "retrieved": retrieved,
            "subtype": subtype,
        },
        "geometry": {"type": "Point", "coordinates": [round(lon, 6),
                                                      round(lat, 6)]},
    }


def _norm(s):
    keep = "".join(c if c.isalnum() else " " for c in (s or "").lower())
    drop = {"the", "of", "and", "inc", "llc", "co", "school", "chicago",
            "public", "center", "centre", "hospital", "pharmacy", "st"}
    return " ".join(w for w in keep.split() if w not in drop)


def dedupe(feats, radius_m=100.0):
    """Drop exact source_id repeats, then near-duplicate name+location pairs.

    Two passes because the failure modes differ: Overpass returns the same
    element once per sub-bbox it touches (id collision), while a chain
    pharmacy mapped as both a node and a building way is one place under two
    ids at nearly the same spot.
    """
    seen, out = set(), []
    for f in feats:
        k = (f["properties"]["source"], f["properties"]["source_id"])
        if k in seen:
            continue
        seen.add(k)
        out.append(f)
    kept = []
    for f in out:
        p = f["geometry"]["coordinates"]
        n = _norm(f["properties"]["name"])
        dup = False
        for g in kept:
            if n and n == _norm(g["properties"]["name"]) and \
                    metres_apart(p, g["geometry"]["coordinates"]) <= radius_m:
                dup = True
                break
        if not dup:
            kept.append(f)
    return kept


def write(category, feats, out_dir=OUT_DIR):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{category}.geojson")
    feats = sorted(feats, key=lambda f: (f["properties"]["name"],
                                         f["properties"]["source_id"]))
    fc = {
        "type": "FeatureCollection",
        "name": category,
        "crs": {"type": "name",
                "properties": {"name": "urn:ogc:def:crs:OGC:1.3/CRS84"}},
        "features": feats,
    }
    with open(path, "w") as fh:
        json.dump(fc, fh, indent=1)
        fh.write("\n")
    print(f"  wrote {len(feats):5d} -> {os.path.relpath(path, REPO)}")
    return path
