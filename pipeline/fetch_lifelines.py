#!/usr/bin/env python3
"""Fetch the lifeline PLACES for the City of Chicago (roadmap Phase 2a).

Public places people depend on when a storm arrives, one small GeoJSON per
category in data/lifelines/, clipped to data/aoi/chicago.geojson, EPSG:4326,
standardised to the schema in lifelines_common.py.

    fetch_lifelines.py                 # every category
    fetch_lifelines.py schools grocery # a subset

Sources, all cited in data/SOURCES.md before use:
  schools, fire_stations, police_stations   Chicago Data Portal (Socrata)
  hospitals                                 CMS Care Compare + Census geocoder
  pharmacies, grocery, substations,
  water_wastewater                          OpenStreetMap via Overpass (ODbL)

Nothing here describes the condition, capacity, value or management of
anything. These are locations of public places; that is the whole model.
"""
import datetime as _dt
import json
import sys
import time
import urllib.parse

from lifelines_common import (CATEGORIES, Clip, centroid, dedupe, feature,
                              get_json, overpass, write)

TODAY = _dt.date.today().isoformat()

SOCRATA = "https://data.cityofchicago.org/resource/{}.json?{}"

# Chicago AOI bbox padded a little; the precise clip happens after.
PAD = 0.01


def _bbox(clip):
    xs = [b[0] for b in clip.boxes] + [b[2] for b in clip.boxes]
    ys = [b[1] for b in clip.boxes] + [b[3] for b in clip.boxes]
    return (min(ys) - PAD, min(xs) - PAD, max(ys) + PAD, max(xs) + PAD)


def _socrata(dataset, params):
    url = SOCRATA.format(dataset, urllib.parse.urlencode(params))
    return get_json(url)


# ---------------------------------------------------------------- portal

NCES_PRIVATE = ("https://nces.ed.gov/opengis/rest/services/"
                "K12_School_Locations/EDGE_GEOCODE_PRIVATESCH_2324/MapServer/"
                "0/query?where=UPPER(CITY)%3D%27CHICAGO%27%20AND%20"
                "STATE%3D%27IL%27&outFields=PPIN,NAME,LAT,LON"
                "&returnGeometry=false&f=json&resultRecordCount=2000")


def schools(clip):
    """Every school in the city, from two sources because no single public
    list covers both.

    CPS publishes district-run, charter and contract schools. Private and
    parochial schools — a large share of Chicago's enrolment — appear in
    neither CPS nor any city dataset, so they come from the federal NCES
    Private School Universe Survey geocode file. `source` tells the two
    apart; `subtype` is CPS's grade band (ES / HS) on CPS rows and the
    literal `private` on NCES rows, which is the only kind distinction
    either source publishes.
    """
    out = []
    for r in _socrata("pb6d-zzuh", {"$limit": 5000}):
        try:
            lon, lat = float(r["long"]), float(r["lat"])
        except (KeyError, TypeError, ValueError):
            continue
        if not clip.contains(lon, lat):
            continue
        out.append(feature(r.get("short_name"), "schools",
                           "chicago_data_portal_pb6d-zzuh", r["school_id"],
                           TODAY, lon, lat, r.get("grade_cat")))
    print(f"  CPS SY2526: {len(out)} in AOI")
    n0 = len(out)
    for f in get_json(NCES_PRIVATE)["features"]:
        a = f["attributes"]
        try:
            lon, lat = float(a["LON"]), float(a["LAT"])
        except (KeyError, TypeError, ValueError):
            continue
        if not clip.contains(lon, lat):
            continue
        out.append(feature(a.get("NAME"), "schools",
                           "nces_edge_geocode_privatesch_2324", a["PPIN"],
                           TODAY, lon, lat, "private"))
    print(f"  NCES private 2023-24: {len(out) - n0} in AOI")
    return out


def fire_stations(clip):
    rows = _socrata("28km-gtjn", {"$limit": 5000, "$select": ":id,name,address,location"})
    out = []
    for r in rows:
        loc = r.get("location") or {}
        try:
            lon, lat = float(loc["longitude"]), float(loc["latitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if not clip.contains(lon, lat):
            continue
        nm = r.get("name") or ""
        out.append(feature(f"Fire station {nm}".strip(), "fire_stations",
                           "chicago_data_portal_28km-gtjn", r[":id"],
                           TODAY, lon, lat, None))
    return out


def police_stations(clip):
    rows = _socrata("z8bn-74gv", {"$limit": 5000,
                                  "$select": ":id,district,district_name,latitude,longitude"})
    out = []
    for r in rows:
        try:
            lon, lat = float(r["longitude"]), float(r["latitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if not clip.contains(lon, lat):
            continue
        nm = r.get("district_name") or r.get("district") or ""
        label = nm if nm.lower() == "headquarters" else f"{nm} District station"
        out.append(feature(label, "police_stations",
                           "chicago_data_portal_z8bn-74gv", r[":id"],
                           TODAY, lon, lat, None))
    return out


# ---------------------------------------------------------------- hospitals

CENSUS_GEOCODER = ("https://geocoding.geo.census.gov/geocoder/locations/"
                   "onelineaddress?address={}&benchmark=Public_AR_Current"
                   "&format=json")

CMS_QUERY = ("https://data.cms.gov/provider-data/api/1/datastore/query/"
             "xubh-q36u/0?limit=500"
             "&conditions[0][property]=state"
             "&conditions[0][value]=IL&conditions[0][operator]=%3D"
             "&conditions[1][property]=citytown"
             "&conditions[1][value]=CHICAGO&conditions[1][operator]=%3D")


NOMINATIM = ("https://nominatim.openstreetmap.org/search?q={}"
             "&format=json&limit=1&countrycodes=us")


def _census_geocode(addr):
    url = CENSUS_GEOCODER.format(urllib.parse.quote(addr))
    try:
        m = get_json(url, timeout=60, tries=3)["result"]["addressMatches"]
    except Exception as ex:                           # noqa: BLE001
        print(f"    census geocoder error: {ex}")
        return None
    finally:
        time.sleep(0.5)                                # be polite
    if not m:
        return None
    return float(m[0]["coordinates"]["x"]), float(m[0]["coordinates"]["y"])


def _nominatim_geocode(q):
    """Fallback for the handful of CMS records whose address field is prose
    ("15TH STREET AT CALIFORNIA") rather than a house number the Census
    address-range matcher can resolve. Nominatim is OSM: rows resolved this
    way carry an ODbL obligation, which is why `source` records it."""
    try:
        r = get_json(NOMINATIM.format(urllib.parse.quote(q)), timeout=60,
                     tries=3)
    except Exception as ex:                           # noqa: BLE001
        print(f"    nominatim error: {ex}")
        return None
    finally:
        time.sleep(1.2)                                # Nominatim: 1 req/s
    return (float(r[0]["lon"]), float(r[0]["lat"])) if r else None


# CMS `facility_name` is a legacy 30-character field and a few Chicago
# entries are mangled past the point where any geocoder can find them. The
# fix is a corrected SEARCH STRING, never a hand-typed coordinate — the
# location still comes from a cited geocoder, so the result stays
# reproducible. Keyed by CMS facility_id, with the raw value alongside.
NAME_ALIASES = {
    "143301": "La Rabida Children's Hospital",   # "LARABIDA CHILDRENS HOSPITAL I"
}


def hospitals(clip):
    """CMS Hospital General Information, geocoded with the Census geocoder.

    Chosen over the Chicago portal (whose only hospital layer is a 2011
    shapefile) and over HIFLD (whose hosted hospitals layer is gone — see
    docs/LIFELINES.md) because CMS carries an explicit `emergency_services`
    flag, which is what Phase 2c's access work actually needs.
    """
    rows = get_json(CMS_QUERY)["results"]
    print(f"  CMS: {len(rows)} Medicare-certified hospitals listed in Chicago")
    out = []
    for r in rows:
        name = r["facility_name"].title()
        addr = ", ".join([r["address"], r["citytown"], r["state"],
                          r["zip_code"]])
        src = "cms_hospital_general_information+census_geocoder"
        pt = _census_geocode(addr)
        if pt is None:
            q = NAME_ALIASES.get(r["facility_id"], r["facility_name"])
            print(f"    census no match, falling back to OSM: {q} — {addr}")
            pt = _nominatim_geocode(f"{q}, Chicago, Illinois")
            src = "cms_hospital_general_information+osm_nominatim"
        if pt is None:
            print(f"  UNGEOCODED, DROPPED: {name} — {addr}")
            continue
        lon, lat = pt
        if not clip.contains(lon, lat):
            print(f"  outside AOI, dropped: {name} ({lon:.4f},{lat:.4f})")
            continue
        ed = (r.get("emergency_services") or "").strip().lower() == "yes"
        out.append(feature(name, "hospitals", src, r["facility_id"], TODAY,
                           lon, lat,
                           "with_emergency_department" if ed
                           else "no_emergency_department"))
    return out


# ---------------------------------------------------------------- OSM

def _osm_points(clip, selectors, category, subtype_key, timeout=300):
    """Run an Overpass query over the AOI bbox and reduce every element to a
    point. Ways and relations collapse to their `center`."""
    s, w, n, e = _bbox(clip)
    body = "\n".join(f' nwr[{sel}]({s},{w},{n},{e});' for sel in selectors)
    q = f"[out:json][timeout:{timeout}];\n(\n{body}\n);\nout center;"
    els = overpass(q, timeout=timeout)
    out = []
    for el in els:
        if "center" in el:
            lon, lat = el["center"]["lon"], el["center"]["lat"]
        elif "lon" in el:
            lon, lat = el["lon"], el["lat"]
        elif "geometry" in el:
            lon, lat = centroid([[p["lon"], p["lat"]] for p in el["geometry"]])
        else:
            continue
        if not clip.contains(lon, lat):
            continue
        tags = el.get("tags", {})
        sub = None
        for k in subtype_key:
            if tags.get(k):
                sub = tags[k]
                break
        out.append(feature(tags.get("name"), category, "openstreetmap",
                           f"{el['type']}/{el['id']}", TODAY, lon, lat, sub))
    return out


def pharmacies(clip):
    return _osm_points(clip, ['"amenity"="pharmacy"',
                              '"healthcare"="pharmacy"'],
                       "pharmacies", ["brand", "operator"])


def grocery(clip):
    return _osm_points(clip, ['"shop"="supermarket"',
                              '"shop"="grocery"',
                              '"shop"="greengrocer"'],
                       "grocery", ["shop"])


def substations(clip):
    return _osm_points(clip, ['"power"="substation"'],
                       "substations", ["substation"])


def water_wastewater(clip):
    return _osm_points(clip, ['"man_made"="wastewater_plant"',
                              '"man_made"="water_works"'],
                       "water_wastewater", ["man_made"])


FETCHERS = {
    "schools": schools,
    "fire_stations": fire_stations,
    "police_stations": police_stations,
    "hospitals": hospitals,
    "pharmacies": pharmacies,
    "grocery": grocery,
    "substations": substations,
    "water_wastewater": water_wastewater,
}


def main(argv):
    wanted = argv or CATEGORIES
    bad = [c for c in wanted if c not in FETCHERS]
    if bad:
        sys.exit(f"unknown category: {bad}; choose from {CATEGORIES}")
    clip = Clip()
    counts = {}
    for cat in wanted:
        print(f"{cat}:")
        feats = FETCHERS[cat](clip)
        raw = len(feats)
        feats = dedupe(feats)
        counts[cat] = len(feats)
        print(f"  {raw} in AOI, {raw - len(feats)} duplicates dropped")
        write(cat, feats)
    print("\ncounts: " + json.dumps(counts, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
