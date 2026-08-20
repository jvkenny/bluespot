# Validation — the scenario depths against Chicago 311

Phase 1c of the roadmap. Two model versions are scored here, against the same
storms, the same complaint sets, the same null models and the same seed:

- **v0.3**, the published citywide model — uniform runoff coefficient
  C = 0.55, uniform drainage term D = 10 mm. Scored 2026-08-19. The baseline.
- **v0.4**, the Phase 1a physics upgrade — per-cell NRCS curve number (TR-55)
  from NLCD 2021 cover and imperviousness plus SSURGO hydrologic soil groups,
  D still uniform. Re-scored the same day. See "v0.4 re-score" below.

The body of this document describes the method and the v0.3 baseline in full;
the v0.4 section is a strict comparison against it. **Short version: v0.4 is
better-founded physics that the 311 test cannot distinguish from the old
guess — the skill ratio went 1.26 → 1.20.**

Everything here is produced by `pipeline/validate_311.py`, deterministically,
from public sources listed in `data/SOURCES.md` (entries 9-11).

---

## The verdict, first

*(These are the **v0.3 baseline** numbers. The v0.4 curve-number re-score
moves the headline ratio to 1.20 and changes none of the conclusions below —
see "v0.4 re-score".)*

**Water on the street: real but modest skill.** Pooled over five storms, at a
25 m tolerance and a ponded depth of at least 30 cm, **19.6%** of
water-on-street complaints fell inside the model's footprint, against
**15.5%** expected from the sharpest null model — the same complaint type on
rain-free days. A ratio of **1.26**. Against a purely geometric null (random
points on the street network) the ratio is **1.50**.

**Water in the basement: no skill, and that is the right answer.** Same test,
ratio **1.05** against the dry-day null (z = +1.9, p = 0.06 — not
significant). Basements flood when the combined sewer surcharges. The model
contains no sewer. It should not be able to predict this, and it cannot.

**At the product's own definition of wet — 5 cm — the map cannot be scored at
all.** The published `b75_2yr` layer calls 9.8% of the city wet at ≥5 cm, and
88% of *random* points in the city sit within 25 m of one of those cells. A
test whose null is 88% cannot distinguish anything. Every ≥5 cm ratio at 25 m
or wider — pooled or per event, all three nulls — falls between 1.00 and 1.14.
This is the single most important thing this exercise
found, and it is about the metric as much as the model: **the ≥5 cm layer is
an envelope, not a screen.**

**And skill runs the wrong way with storm size.** The two largest events
scored (4.01 and 3.39 in) have the *lowest* street-complaint ratios, 1.22 and
1.13; the mid-size 2.35 in event has the highest, 1.47. A uniform-rain model
scored against increasingly convective, increasingly patchy storms should
behave exactly like that — but it is the opposite of what a tool meant to help
before a big storm needs to do.

So: the terrain screening beats the null, but only when you ask it about
ponding deep enough to matter, only for the phenomenon it actually models, and
only by about a quarter to a half over chance — least of all for the storms
that matter most. It is a weak-but-real signal. It is nowhere near strong
enough to justify highlighting specific blocks from a forecast, which is what
Phase 4 wants to do.

---

## What was compared

### The complaints

Chicago 311 Service Requests, dataset `v6vf-nfxy` (2018-07-01 onward — the
current 311 system; the pre-2019 legacy dataset is not used). Every SR type in
the dataset that is plausibly a report of water where it should not be,
discovered by grouping the dataset itself rather than guessing. Note the
City's label is "Water **On** Street", not "water in street".

| group | SR types | geocoded records |
|---|---|---|
| **street** | Water On Street Complaint | 80,383 |
| **basement** | Water in Basement Complaint | 69,795 |
| *sewer* (secondary) | Sewer Cleaning Inspection Request, Sewer Cave-In Inspection Request, Alley Sewer Inspection Request | 138,766 |

288,944 geocoded records in total, 99.8% of all records of those types.

**Street and basement are scored separately and never pooled.** They are
different physical events. Surface ponding on terrain is what this model
claims to describe; a wet basement is a sewer event that happens to correlate
with rain. The sewer group is reported alongside as a third, clearly secondary
signal — those requests describe the pipe, not the puddle.

Geocodes are **block-level**: the City geocodes to an address range, not a
parcel. That is the entire reason for reporting tolerance radii of 0, 25, 50
and 100 m rather than a single point-in-polygon test.

Between 24% and 29% of water-on-street records in the event windows carry the
`duplicate` flag — a second call about the same problem. They are kept. Each
is a real person reporting water at a real location, and every null model is
subject to the same clustering.

### The storms

Chosen from the 2019-2026 daily record at the two official NWS climate
stations, to span sizes with non-overlapping windows. The event total is the
**mean of O'Hare and Midway**, and the mapping to a bookmark is nearest in
inches.

Rain totals are not hardcoded — the script fetches them from ACIS at run time.

### The maps

The five published citywide products in `<data_root>/citywide/`: the four rain
bookmarks (1.0, 3.34, 7.58, 8.57 in) and the static max-fill envelope. Each
event is scored primarily at its nearest bookmark; the appendix scores every
point set against every bookmark.

Each raster is thresholded to a boolean "ponded" mask at two depths:

- **≥5 cm**, the product's own `MIN_DEPTH` — the headline definition;
- **≥30 cm**, added because ≥5 cm saturates. 30 cm is roughly where ponding
  stops being cosmetic, and is the passability threshold Phase 2b plans to
  cite to FHWA/NWS vehicle-stall guidance.

### The null models

A hit rate without a baseline is a number with no meaning. Three baselines,
weakest to strongest:

1. **uniform** — 100,000 points drawn uniformly over the 598.8 km² city
   polygon. Answers "how often would you hit by pointing anywhere?"
2. **street network** — 100,000 points drawn length-weighted along 6,633 km of
   Chicago street centerlines (classes 1-4, status in-service). Expressways
   are deliberately *included*: leaving them out would strip the deepest pools
   in the city out of the null and flatter the model.
3. **dry-day, same type** — the *same* 311 complaint types on the 1,394 days
   in the record with under 0.10 in at both stations on the day and the two
   days before. This is the sharpest control available, because it shares the
   complaint geography, the reporting behaviour, the geocoding convention and
   the demographic distribution with the event set. The only thing it does not
   share is a storm.

Null 3 is the one to read. Nulls 1 and 2 flatter the model, because they do
not know that 311 calls come from where people are.

---

## Method

1. Reproject every point to EPSG:26916 and snap to the depth raster's 1 m
   grid. Discard points outside the raster or outside the city polygon (a
   handful: 881 of 100,000 street-null points, 0-3 per event window).
2. Build the ponded mask for a scenario/threshold pair as one boolean array
   over the whole 40,000 × 50,000 city grid, padded by 100 cells. NaN (open
   water, outside the city) counts as dry.
3. For each of the 271,335 unique locations, find the smallest radius in
   {0, 25, 50, 100} m at which a ponded cell falls inside a Euclidean disk
   centred on the point. Each unique location is tested once per
   scenario/threshold and the answer is shared by every point set that
   contains it.
4. Hit rate = fraction of scored points whose first-hit radius is ≤ R, with a
   Wilson 95% interval.
5. Skill = event hit rate ÷ null hit rate, with a two-proportion z-test. The
   pooled statistic scores each event against *its own* bookmark and sums:
   expected = Σ n_event × null rate at that event's bookmark, with a
   Poisson-binomial normal approximation for z.

Determinism: one fixed seed (20260819) governs all null sampling; network
pulls are cached to `<data_root>/validation/` on Drive and reused.

---

## Results

<!-- BEGIN GENERATED TABLES -->

<!-- generated by pipeline/validate_311.py — do not hand-edit -->

### 1. Events scored

| event | O'Hare in | Midway in | event total in | citywide gauges (n, min / median / max) | nearest bookmark |
|---|---|---|---|---|---|
| 2023-07-02 | 3.35 | 4.68 | **4.01** | 32, 0.00 / 0.73 / 4.68 | b75_2yr (3.34 in) |
| 2020-05-17 | 3.11 | 3.67 | **3.39** | 37, 0.70 / 1.07 / 3.95 | b75_2yr (3.34 in) |
| 2026-07-27 | 1.76 | 2.94 | **2.35** | 30, 0.00 / 0.00 / 3.31 | b75_2yr (3.34 in) |
| 2026-08-01 | 1.85 | 1.56 | **1.71** | 28, 0.63 / 1.28 / 2.69 | r10 (1.00 in) |
| 2026-08-09 | 1.34 | 0.72 | **1.03** | 33, 0.00 / 0.00 / 2.32 | r10 (1.00 in) |

Event total = mean of the two official NWS climate stations. The gauge
column is every ACIS station in the Chicago bounding box that reported
that day (ASOS + COOP + CoCoRaHS, mixed observation windows) and is
there to show how much a single citywide number hides.

### 2. Complaint volume — the temporal signal

Complaints per day in each event window (event day + 2 days) against
the dry-day rate over 1394 qualifying dry days.

| event | water on street /day | x dry | water in basement /day | x dry | sewer /day | x dry |
|---|---|---|---|---|---|---|
| 2023-07-02 | 214 | **21x** | 1266 | **117x** | 152 | **4x** |
| 2020-05-17 | 484 | **48x** | 514 | **47x** | 450 | **12x** |
| 2026-07-27 | 316 | **31x** | 295 | **27x** | 234 | **6x** |
| 2026-08-01 | 134 | **13x** | 60 | **6x** | 97 | **3x** |
| 2026-08-09 | 181 | **18x** | 75 | **7x** | 151 | **4x** |
| *dry-day baseline* | 10.1 | 1x | 10.9 | 1x | 36.1 | 1x |

### 3. How much of the city each map covers

The reason tolerance radii saturate. "Reachable" = share of a uniform
random sample of the city within that radius of a ponded cell.

| bookmark | depth | wet km2 | % of city | reachable @25 m | @50 m | @100 m |
|---|---|---|---|---|---|---|
| b70_100yr | >=0.05 m | 84.5 | 14.1% | 89.7% | 97.5% | 99.5% |
| b70_100yr | >=0.30 m | 16.2 | 2.7% | 24.8% | 47.5% | 77.4% |
| b75_100yr | >=0.05 m | 87.9 | 14.7% | 89.9% | 97.5% | 99.5% |
| b75_100yr | >=0.30 m | 18.4 | 3.1% | 25.6% | 48.2% | 77.7% |
| b75_2yr | >=0.05 m | 58.8 | 9.8% | 88.0% | 97.0% | 99.4% |
| b75_2yr | >=0.30 m | 5.5 | 0.9% | 16.9% | 38.4% | 71.3% |
| full | >=0.05 m | 109.7 | 18.3% | 91.1% | 97.9% | 99.5% |
| full | >=0.30 m | 37.5 | 6.3% | 29.7% | 51.6% | 79.3% |
| r10 | >=0.05 m | 13.7 | 2.3% | 81.7% | 95.0% | 99.1% |
| r10 | >=0.30 m | 0.3 | 0.1% | 2.7% | 8.3% | 24.1% |

### 4. Hit rates at ponded depth >= 0.05 m

#### Water On Street Complaint

| point set | bookmark | n | 0 m | 25 m | 50 m | 100 m |
|---|---|---|---|---|---|---|
| 2023-07-02 | b75_2yr | 643 | 7.2% | 97.5% | 99.8% | 100.0% |
| 2020-05-17 | b75_2yr | 1453 | 12.6% | 97.7% | 99.8% | 100.0% |
| 2026-07-27 | b75_2yr | 948 | 9.6% | 97.9% | 99.9% | 100.0% |
| 2026-08-01 | r10 | 401 | 0.7% | 92.0% | 98.0% | 99.8% |
| 2026-08-09 | r10 | 543 | 1.1% | 93.0% | 98.2% | 99.8% |
| *null: street network* | r10 | 99119 | 1.3% | 87.0% | 97.6% | 99.8% |
| *null: street network* | b75_2yr | 99119 | 11.7% | 93.6% | 99.2% | 100.0% |
| *null: uniform in city* | r10 | 100000 | 2.3% | 81.7% | 95.0% | 99.1% |
| *null: uniform in city* | b75_2yr | 100000 | 9.8% | 88.0% | 97.0% | 99.4% |
| *null: same type, dry days* | r10 | 14059 | 1.9% | 91.8% | 98.5% | 99.9% |
| *null: same type, dry days* | b75_2yr | 14059 | 8.1% | 96.3% | 99.9% | 100.0% |

#### Water in Basement Complaint

| point set | bookmark | n | 0 m | 25 m | 50 m | 100 m |
|---|---|---|---|---|---|---|
| 2023-07-02 | b75_2yr | 3799 | 3.7% | 98.8% | 100.0% | 100.0% |
| 2020-05-17 | b75_2yr | 1541 | 6.2% | 98.6% | 99.9% | 100.0% |
| 2026-07-27 | b75_2yr | 886 | 5.9% | 97.7% | 100.0% | 100.0% |
| 2026-08-01 | r10 | 181 | 1.1% | 91.2% | 98.3% | 99.4% |
| 2026-08-09 | r10 | 225 | 0.4% | 89.3% | 96.4% | 100.0% |
| *null: street network* | r10 | 99119 | 1.3% | 87.0% | 97.6% | 99.8% |
| *null: street network* | b75_2yr | 99119 | 11.7% | 93.6% | 99.2% | 100.0% |
| *null: uniform in city* | r10 | 100000 | 2.3% | 81.7% | 95.0% | 99.1% |
| *null: uniform in city* | b75_2yr | 100000 | 9.8% | 88.0% | 97.0% | 99.4% |
| *null: same type, dry days* | r10 | 15133 | 0.7% | 92.7% | 98.3% | 99.7% |
| *null: same type, dry days* | b75_2yr | 15133 | 4.5% | 97.3% | 99.9% | 100.0% |

#### Sewer-related requests

| point set | bookmark | n | 0 m | 25 m | 50 m | 100 m |
|---|---|---|---|---|---|---|
| 2023-07-02 | b75_2yr | 455 | 7.5% | 98.7% | 99.8% | 100.0% |
| 2020-05-17 | b75_2yr | 1350 | 10.7% | 98.6% | 99.9% | 100.0% |
| 2026-07-27 | b75_2yr | 703 | 11.4% | 98.6% | 99.7% | 100.0% |
| 2026-08-01 | r10 | 292 | 2.7% | 93.2% | 98.3% | 99.7% |
| 2026-08-09 | r10 | 453 | 2.9% | 92.7% | 98.0% | 99.8% |
| *null: street network* | r10 | 99119 | 1.3% | 87.0% | 97.6% | 99.8% |
| *null: street network* | b75_2yr | 99119 | 11.7% | 93.6% | 99.2% | 100.0% |
| *null: uniform in city* | r10 | 100000 | 2.3% | 81.7% | 95.0% | 99.1% |
| *null: uniform in city* | b75_2yr | 100000 | 9.8% | 88.0% | 97.0% | 99.4% |
| *null: same type, dry days* | r10 | 50393 | 2.3% | 92.1% | 98.5% | 99.8% |
| *null: same type, dry days* | b75_2yr | 50393 | 8.6% | 96.9% | 99.8% | 100.0% |

#### 4.1 Skill at >=0.05 m — event rate / null rate

**Water On Street Complaint**

| event | null | ratio @0 m | ratio @25 m | ratio @50 m | ratio @100 m | z @0 m | z @25 m | p @25 m |
|---|---|---|---|---|---|---|---|---|
| 2023-07-02 | street network | 0.61 | 1.04 | 1.01 | 1.00 | -3.6 | +4.1 | 4.6e-05 |
| 2023-07-02 | uniform in city | 0.73 | 1.11 | 1.03 | 1.01 | -2.3 | +7.4 | 1.4e-13 |
| 2023-07-02 | same type | 0.88 | 1.01 | 1.00 | 1.00 | -0.9 | +1.6 | 1.2e-01 |
| 2020-05-17 | street network | 1.08 | 1.04 | 1.01 | 1.00 | +1.1 | +6.5 | 1.1e-10 |
| 2020-05-17 | uniform in city | 1.28 | 1.11 | 1.03 | 1.01 | +3.5 | +11.4 | 6.2e-30 |
| 2020-05-17 | same type | 1.55 | 1.01 | 1.00 | 1.00 | +5.8 | +2.7 | 6.2e-03 |
| 2026-07-27 | street network | 0.82 | 1.05 | 1.01 | 1.00 | -2.0 | +5.4 | 5.9e-08 |
| 2026-07-27 | uniform in city | 0.97 | 1.11 | 1.03 | 1.01 | -0.3 | +9.3 | 9.5e-21 |
| 2026-07-27 | same type | 1.18 | 1.02 | 1.00 | 1.00 | +1.6 | +2.5 | 1.3e-02 |
| 2026-08-01 | street network | 0.57 | 1.06 | 1.00 | 1.00 | -1.0 | +3.0 | 2.9e-03 |
| 2026-08-01 | uniform in city | 0.32 | 1.13 | 1.03 | 1.01 | -2.1 | +5.3 | 1.0e-07 |
| 2026-08-01 | same type | 0.40 | 1.00 | 1.00 | 1.00 | -1.7 | +0.2 | 8.7e-01 |
| 2026-08-09 | street network | 0.85 | 1.07 | 1.01 | 1.00 | -0.4 | +4.1 | 3.4e-05 |
| 2026-08-09 | uniform in city | 0.48 | 1.14 | 1.03 | 1.01 | -1.9 | +6.8 | 1.2e-11 |
| 2026-08-09 | same type | 0.59 | 1.01 | 1.00 | 1.00 | -1.3 | +1.0 | 3.1e-01 |

**Water in Basement Complaint**

| event | null | ratio @0 m | ratio @25 m | ratio @50 m | ratio @100 m | z @0 m | z @25 m | p @25 m |
|---|---|---|---|---|---|---|---|---|
| 2023-07-02 | street network | 0.32 | 1.06 | 1.01 | 1.00 | -15.2 | +13.1 | 4.9e-39 |
| 2023-07-02 | uniform in city | 0.38 | 1.12 | 1.03 | 1.01 | -12.6 | +20.3 | 4.9e-92 |
| 2023-07-02 | same type | 0.83 | 1.02 | 1.00 | 1.00 | -2.1 | +5.3 | 9.7e-08 |
| 2020-05-17 | street network | 0.53 | 1.05 | 1.01 | 1.00 | -6.6 | +8.1 | 5.4e-16 |
| 2020-05-17 | uniform in city | 0.63 | 1.12 | 1.03 | 1.01 | -4.7 | +12.8 | 1.5e-37 |
| 2020-05-17 | same type | 1.39 | 1.01 | 1.00 | 1.00 | +3.1 | +3.1 | 1.7e-03 |
| 2026-07-27 | street network | 0.50 | 1.04 | 1.01 | 1.00 | -5.4 | +5.1 | 4.1e-07 |
| 2026-07-27 | uniform in city | 0.60 | 1.11 | 1.03 | 1.01 | -4.0 | +8.9 | 5.8e-19 |
| 2026-07-27 | same type | 1.31 | 1.00 | 1.00 | 1.00 | +1.9 | +0.8 | 4.4e-01 |
| 2026-08-01 | street network | 0.85 | 1.05 | 1.01 | 1.00 | -0.2 | +1.7 | 9.7e-02 |
| 2026-08-01 | uniform in city | 0.48 | 1.12 | 1.04 | 1.00 | -1.1 | +3.3 | 1.0e-03 |
| 2026-08-01 | same type | 1.58 | 0.98 | 1.00 | 1.00 | +0.6 | -0.8 | 4.4e-01 |
| 2026-08-09 | street network | 0.34 | 1.03 | 0.99 | 1.00 | -1.1 | +1.0 | 3.0e-01 |
| 2026-08-09 | uniform in city | 0.19 | 1.09 | 1.02 | 1.01 | -1.9 | +2.9 | 3.2e-03 |
| 2026-08-09 | same type | 0.63 | 0.96 | 0.98 | 1.00 | -0.5 | -1.9 | 5.7e-02 |

**Sewer-related requests**

| event | null | ratio @0 m | ratio @25 m | ratio @50 m | ratio @100 m | z @0 m | z @25 m | p @25 m |
|---|---|---|---|---|---|---|---|---|
| 2023-07-02 | street network | 0.64 | 1.05 | 1.01 | 1.00 | -2.8 | +4.4 | 8.7e-06 |
| 2023-07-02 | uniform in city | 0.76 | 1.12 | 1.03 | 1.01 | -1.7 | +7.0 | 2.6e-12 |
| 2023-07-02 | same type | 0.87 | 1.02 | 1.00 | 1.00 | -0.9 | +2.2 | 3.1e-02 |
| 2020-05-17 | street network | 0.91 | 1.05 | 1.01 | 1.00 | -1.1 | +7.5 | 5.5e-14 |
| 2020-05-17 | uniform in city | 1.08 | 1.12 | 1.03 | 1.01 | +1.0 | +11.9 | 7.5e-33 |
| 2020-05-17 | same type | 1.24 | 1.02 | 1.00 | 1.00 | +2.6 | +3.5 | 4.5e-04 |
| 2026-07-27 | street network | 0.97 | 1.05 | 1.00 | 1.00 | -0.2 | +5.4 | 6.2e-08 |
| 2026-07-27 | uniform in city | 1.16 | 1.12 | 1.03 | 1.01 | +1.4 | +8.6 | 7.4e-18 |
| 2026-07-27 | same type | 1.32 | 1.02 | 1.00 | 1.00 | +2.6 | +2.5 | 1.2e-02 |
| 2026-08-01 | street network | 2.10 | 1.07 | 1.01 | 1.00 | +2.2 | +3.1 | 1.8e-03 |
| 2026-08-01 | uniform in city | 1.19 | 1.14 | 1.04 | 1.01 | +0.5 | +5.0 | 4.6e-07 |
| 2026-08-01 | same type | 1.21 | 1.01 | 1.00 | 1.00 | +0.5 | +0.6 | 5.2e-01 |
| 2026-08-09 | street network | 2.20 | 1.07 | 1.00 | 1.00 | +2.9 | +3.6 | 3.1e-04 |
| 2026-08-09 | uniform in city | 1.25 | 1.13 | 1.03 | 1.01 | +0.8 | +6.0 | 1.6e-09 |
| 2026-08-09 | same type | 1.26 | 1.01 | 1.00 | 1.00 | +0.9 | +0.5 | 6.4e-01 |

#### 4.2 Pooled across all five storms, >=0.05 m

Each event's complaints are scored against ITS OWN nearest bookmark,
then pooled. Expected = sum over events of n_event x null rate at
that event's bookmark; z is the normal approximation to the
Poisson-binomial. Spatial clustering is NOT accounted for, so treat
these p-values as an upper bound on confidence.

| complaint type | null | radius | observed | expected | ratio | z | p |
|---|---|---|---|---|---|---|---|
| Water On Street Complaint | street network | 0 m | 329 / 3988 (8.2%) | 368 (9.2%) | **0.89** | -2.1 | 3.2e-02 |
| Water On Street Complaint | street network | 25 m | 3849 / 3988 (96.5%) | 3669 (92.0%) | **1.05** | +10.5 | 5.3e-26 |
| Water On Street Complaint | street network | 50 m | 3965 / 3988 (99.4%) | 3941 (98.8%) | **1.01** | +3.5 | 4.8e-04 |
| Water On Street Complaint | street network | 100 m | 3986 / 3988 (99.9%) | 3985 (99.9%) | **1.00** | +0.5 | 6.0e-01 |
| Water On Street Complaint | uniform in city | 0 m | 329 / 3988 (8.2%) | 321 (8.1%) | **1.02** | +0.4 | 6.6e-01 |
| Water On Street Complaint | uniform in city | 25 m | 3849 / 3988 (96.5%) | 3451 (86.5%) | **1.12** | +18.5 | 1.6e-76 |
| Water On Street Complaint | uniform in city | 50 m | 3965 / 3988 (99.4%) | 3848 (96.5%) | **1.03** | +10.1 | 8.2e-24 |
| Water On Street Complaint | uniform in city | 100 m | 3986 / 3988 (99.9%) | 3961 (99.3%) | **1.01** | +4.8 | 1.3e-06 |
| Water On Street Complaint | same type | 0 m | 329 / 3988 (8.2%) | 265 (6.7%) | **1.24** | +4.1 | 4.6e-05 |
| Water On Street Complaint | same type | 25 m | 3849 / 3988 (96.5%) | 3799 (95.3%) | **1.01** | +3.7 | 1.8e-04 |
| Water On Street Complaint | same type | 50 m | 3965 / 3988 (99.4%) | 3969 (99.5%) | **1.00** | -0.9 | 3.6e-01 |
| Water On Street Complaint | same type | 100 m | 3986 / 3988 (99.9%) | 3987 (100.0%) | **1.00** | -0.4 | 6.8e-01 |
| Water in Basement Complaint | street network | 0 m | 292 / 6632 (4.4%) | 732 (11.0%) | **0.40** | -17.3 | 4.1e-67 |
| Water in Basement Complaint | street network | 25 m | 6505 / 6632 (98.1%) | 6178 (93.2%) | **1.05** | +15.9 | 4.5e-57 |
| Water in Basement Complaint | street network | 50 m | 6620 / 6632 (99.8%) | 6574 (99.1%) | **1.01** | +6.1 | 1.1e-09 |
| Water in Basement Complaint | street network | 100 m | 6631 / 6632 (100.0%) | 6629 (100.0%) | **1.00** | +1.0 | 3.3e-01 |
| Water in Basement Complaint | uniform in city | 0 m | 292 / 6632 (4.4%) | 622 (9.4%) | **0.47** | -13.9 | 3.6e-44 |
| Water in Basement Complaint | uniform in city | 25 m | 6505 / 6632 (98.1%) | 5812 (87.6%) | **1.12** | +25.9 | 1.6e-147 |
| Water in Basement Complaint | uniform in city | 50 m | 6620 / 6632 (99.8%) | 6423 (96.9%) | **1.03** | +13.8 | 1.4e-43 |
| Water in Basement Complaint | uniform in city | 100 m | 6631 / 6632 (100.0%) | 6591 (99.4%) | **1.01** | +6.3 | 3.2e-10 |
| Water in Basement Complaint | same type | 0 m | 292 / 6632 (4.4%) | 283 (4.3%) | **1.03** | +0.6 | 5.7e-01 |
| Water in Basement Complaint | same type | 25 m | 6505 / 6632 (98.1%) | 6435 (97.0%) | **1.01** | +5.1 | 3.7e-07 |
| Water in Basement Complaint | same type | 50 m | 6620 / 6632 (99.8%) | 6617 (99.8%) | **1.00** | +0.8 | 4.0e-01 |
| Water in Basement Complaint | same type | 100 m | 6631 / 6632 (100.0%) | 6631 (100.0%) | **1.00** | +0.1 | 9.0e-01 |
| Sewer-related requests | street network | 0 m | 279 / 3253 (8.6%) | 303 (9.3%) | **0.92** | -1.4 | 1.5e-01 |
| Sewer-related requests | street network | 25 m | 3165 / 3253 (97.3%) | 2995 (92.1%) | **1.06** | +11.1 | 1.3e-28 |
| Sewer-related requests | street network | 50 m | 3234 / 3253 (99.4%) | 3215 (98.8%) | **1.01** | +3.1 | 2.2e-03 |
| Sewer-related requests | street network | 100 m | 3251 / 3253 (99.9%) | 3251 (99.9%) | **1.00** | +0.2 | 8.4e-01 |
| Sewer-related requests | uniform in city | 0 m | 279 / 3253 (8.6%) | 264 (8.1%) | **1.06** | +1.0 | 3.4e-01 |
| Sewer-related requests | uniform in city | 25 m | 3165 / 3253 (97.3%) | 2817 (86.6%) | **1.12** | +18.0 | 3.2e-72 |
| Sewer-related requests | uniform in city | 50 m | 3234 / 3253 (99.4%) | 3140 (96.5%) | **1.03** | +9.0 | 1.6e-19 |
| Sewer-related requests | uniform in city | 100 m | 3251 / 3253 (99.9%) | 3231 (99.3%) | **1.01** | +4.3 | 1.8e-05 |
| Sewer-related requests | same type | 0 m | 279 / 3253 (8.6%) | 233 (7.2%) | **1.20** | +3.1 | 1.7e-03 |
| Sewer-related requests | same type | 25 m | 3165 / 3253 (97.3%) | 3118 (95.8%) | **1.02** | +4.2 | 2.8e-05 |
| Sewer-related requests | same type | 50 m | 3234 / 3253 (99.4%) | 3237 (99.5%) | **1.00** | -0.7 | 5.1e-01 |
| Sewer-related requests | same type | 100 m | 3251 / 3253 (99.9%) | 3251 (99.9%) | **1.00** | -0.2 | 8.2e-01 |

### 5. Hit rates at ponded depth >= 0.30 m

#### Water On Street Complaint

| point set | bookmark | n | 0 m | 25 m | 50 m | 100 m |
|---|---|---|---|---|---|---|
| 2023-07-02 | b75_2yr | 643 | 0.8% | 23.5% | 44.0% | 71.4% |
| 2020-05-17 | b75_2yr | 1453 | 1.0% | 21.9% | 40.4% | 69.6% |
| 2026-07-27 | b75_2yr | 948 | 1.7% | 28.4% | 47.6% | 74.4% |
| 2026-08-01 | r10 | 401 | 0.0% | 4.7% | 11.7% | 26.4% |
| 2026-08-09 | r10 | 543 | 0.0% | 4.4% | 11.2% | 26.2% |
| *null: street network* | r10 | 99119 | 0.1% | 2.2% | 7.7% | 22.6% |
| *null: street network* | b75_2yr | 99119 | 1.1% | 16.5% | 37.7% | 71.2% |
| *null: uniform in city* | r10 | 100000 | 0.1% | 2.7% | 8.3% | 24.1% |
| *null: uniform in city* | b75_2yr | 100000 | 0.9% | 16.9% | 38.4% | 71.3% |
| *null: same type, dry days* | r10 | 14059 | 0.0% | 3.3% | 9.6% | 25.0% |
| *null: same type, dry days* | b75_2yr | 14059 | 1.0% | 19.3% | 40.9% | 72.5% |

#### Water in Basement Complaint

| point set | bookmark | n | 0 m | 25 m | 50 m | 100 m |
|---|---|---|---|---|---|---|
| 2023-07-02 | b75_2yr | 3799 | 0.2% | 15.2% | 32.0% | 62.5% |
| 2020-05-17 | b75_2yr | 1541 | 0.5% | 17.7% | 34.7% | 65.2% |
| 2026-07-27 | b75_2yr | 886 | 1.0% | 24.7% | 45.0% | 72.9% |
| 2026-08-01 | r10 | 181 | 0.0% | 2.8% | 7.7% | 19.9% |
| 2026-08-09 | r10 | 225 | 0.0% | 4.0% | 10.2% | 25.3% |
| *null: street network* | r10 | 99119 | 0.1% | 2.2% | 7.7% | 22.6% |
| *null: street network* | b75_2yr | 99119 | 1.1% | 16.5% | 37.7% | 71.2% |
| *null: uniform in city* | r10 | 100000 | 0.1% | 2.7% | 8.3% | 24.1% |
| *null: uniform in city* | b75_2yr | 100000 | 0.9% | 16.9% | 38.4% | 71.3% |
| *null: same type, dry days* | r10 | 15133 | 0.0% | 2.1% | 5.6% | 16.9% |
| *null: same type, dry days* | b75_2yr | 15133 | 0.4% | 16.4% | 33.7% | 62.7% |

#### Sewer-related requests

| point set | bookmark | n | 0 m | 25 m | 50 m | 100 m |
|---|---|---|---|---|---|---|
| 2023-07-02 | b75_2yr | 455 | 0.9% | 19.3% | 39.3% | 64.8% |
| 2020-05-17 | b75_2yr | 1350 | 0.7% | 23.4% | 42.3% | 71.5% |
| 2026-07-27 | b75_2yr | 703 | 1.1% | 24.9% | 47.2% | 72.8% |
| 2026-08-01 | r10 | 292 | 0.0% | 1.4% | 7.5% | 19.5% |
| 2026-08-09 | r10 | 453 | 0.0% | 3.5% | 9.7% | 21.9% |
| *null: street network* | r10 | 99119 | 0.1% | 2.2% | 7.7% | 22.6% |
| *null: street network* | b75_2yr | 99119 | 1.1% | 16.5% | 37.7% | 71.2% |
| *null: uniform in city* | r10 | 100000 | 0.1% | 2.7% | 8.3% | 24.1% |
| *null: uniform in city* | b75_2yr | 100000 | 0.9% | 16.9% | 38.4% | 71.3% |
| *null: same type, dry days* | r10 | 50393 | 0.0% | 2.5% | 7.5% | 21.6% |
| *null: same type, dry days* | b75_2yr | 50393 | 0.7% | 18.1% | 37.5% | 69.2% |

#### 5.1 Skill at >=0.30 m — event rate / null rate

**Water On Street Complaint**

| event | null | ratio @0 m | ratio @25 m | ratio @50 m | ratio @100 m | z @0 m | z @25 m | p @25 m |
|---|---|---|---|---|---|---|---|---|
| 2023-07-02 | street network | 0.70 | 1.43 | 1.17 | 1.00 | -0.8 | +4.8 | 1.7e-06 |
| 2023-07-02 | uniform in city | 0.83 | 1.39 | 1.15 | 1.00 | -0.4 | +4.4 | 8.9e-06 |
| 2023-07-02 | same type | 0.81 | 1.22 | 1.08 | 0.99 | -0.5 | +2.6 | 8.9e-03 |
| 2020-05-17 | street network | 0.93 | 1.33 | 1.07 | 0.98 | -0.3 | +5.5 | 3.3e-08 |
| 2020-05-17 | uniform in city | 1.11 | 1.30 | 1.05 | 0.98 | +0.4 | +5.0 | 4.8e-07 |
| 2020-05-17 | same type | 1.08 | 1.13 | 0.99 | 0.96 | +0.3 | +2.4 | 1.8e-02 |
| 2026-07-27 | street network | 1.51 | 1.72 | 1.26 | 1.04 | +1.7 | +9.8 | 9.4e-23 |
| 2026-07-27 | uniform in city | 1.81 | 1.68 | 1.24 | 1.04 | +2.4 | +9.4 | 7.4e-21 |
| 2026-07-27 | same type | 1.76 | 1.47 | 1.16 | 1.03 | +2.2 | +6.8 | 1.3e-11 |
| 2026-08-01 | street network | 0.00 | 2.12 | 1.53 | 1.17 | -0.5 | +3.4 | 7.2e-04 |
| 2026-08-01 | uniform in city | 0.00 | 1.77 | 1.42 | 1.10 | -0.5 | +2.5 | 1.1e-02 |
| 2026-08-01 | same type | 0.00 | 1.43 | 1.23 | 1.06 | -0.4 | +1.6 | 1.2e-01 |
| 2026-08-09 | street network | 0.00 | 1.98 | 1.47 | 1.16 | -0.6 | +3.4 | 6.0e-04 |
| 2026-08-09 | uniform in city | 0.00 | 1.65 | 1.36 | 1.08 | -0.6 | +2.5 | 1.2e-02 |
| 2026-08-09 | same type | 0.00 | 1.33 | 1.18 | 1.04 | -0.5 | +1.4 | 1.6e-01 |

**Water in Basement Complaint**

| event | null | ratio @0 m | ratio @25 m | ratio @50 m | ratio @100 m | z @0 m | z @25 m | p @25 m |
|---|---|---|---|---|---|---|---|---|
| 2023-07-02 | street network | 0.19 | 0.93 | 0.85 | 0.88 | -5.3 | -2.0 | 4.6e-02 |
| 2023-07-02 | uniform in city | 0.23 | 0.90 | 0.83 | 0.88 | -4.6 | -2.7 | 7.6e-03 |
| 2023-07-02 | same type | 0.54 | 0.93 | 0.95 | 1.00 | -1.7 | -1.7 | 8.6e-02 |
| 2020-05-17 | street network | 0.47 | 1.07 | 0.92 | 0.91 | -2.2 | +1.2 | 2.1e-01 |
| 2020-05-17 | uniform in city | 0.56 | 1.04 | 0.90 | 0.91 | -1.7 | +0.8 | 4.3e-01 |
| 2020-05-17 | same type | 1.33 | 1.08 | 1.03 | 1.04 | +0.8 | +1.3 | 2.0e-01 |
| 2026-07-27 | street network | 0.91 | 1.50 | 1.19 | 1.02 | -0.3 | +6.6 | 4.5e-11 |
| 2026-07-27 | uniform in city | 1.09 | 1.46 | 1.17 | 1.02 | +0.3 | +6.2 | 6.5e-10 |
| 2026-07-27 | same type | 2.61 | 1.51 | 1.34 | 1.16 | +2.8 | +6.4 | 1.2e-10 |
| 2026-08-01 | street network | 0.00 | 1.24 | 1.01 | 0.88 | -0.4 | +0.5 | 6.3e-01 |
| 2026-08-01 | uniform in city | 0.00 | 1.03 | 0.94 | 0.82 | -0.3 | +0.1 | 9.4e-01 |
| 2026-08-01 | same type | 0.00 | 1.30 | 1.38 | 1.18 | -0.1 | +0.6 | 5.5e-01 |
| 2026-08-09 | street network | 0.00 | 1.79 | 1.34 | 1.12 | -0.4 | +1.8 | 7.3e-02 |
| 2026-08-09 | uniform in city | 0.00 | 1.49 | 1.24 | 1.05 | -0.4 | +1.2 | 2.2e-01 |
| 2026-08-09 | same type | 0.00 | 1.89 | 1.83 | 1.50 | -0.1 | +1.9 | 5.4e-02 |

**Sewer-related requests**

| event | null | ratio @0 m | ratio @25 m | ratio @50 m | ratio @100 m | z @0 m | z @25 m | p @25 m |
|---|---|---|---|---|---|---|---|---|
| 2023-07-02 | street network | 0.79 | 1.17 | 1.04 | 0.91 | -0.5 | +1.7 | 9.9e-02 |
| 2023-07-02 | uniform in city | 0.94 | 1.14 | 1.02 | 0.91 | -0.1 | +1.4 | 1.6e-01 |
| 2023-07-02 | same type | 1.19 | 1.07 | 1.05 | 0.94 | +0.3 | +0.7 | 5.0e-01 |
| 2020-05-17 | street network | 0.60 | 1.42 | 1.12 | 1.00 | -1.6 | +6.8 | 9.1e-12 |
| 2020-05-17 | uniform in city | 0.71 | 1.39 | 1.10 | 1.00 | -1.0 | +6.3 | 2.4e-10 |
| 2020-05-17 | same type | 0.90 | 1.29 | 1.13 | 1.03 | -0.3 | +5.0 | 6.9e-07 |
| 2026-07-27 | street network | 1.02 | 1.51 | 1.25 | 1.02 | +0.1 | +6.0 | 2.0e-09 |
| 2026-07-27 | uniform in city | 1.22 | 1.47 | 1.23 | 1.02 | +0.6 | +5.6 | 1.8e-08 |
| 2026-07-27 | same type | 1.54 | 1.37 | 1.26 | 1.05 | +1.2 | +4.6 | 3.8e-06 |
| 2026-08-01 | street network | 0.00 | 0.61 | 0.98 | 0.86 | -0.5 | -1.0 | 3.2e-01 |
| 2026-08-01 | uniform in city | 0.00 | 0.51 | 0.91 | 0.81 | -0.4 | -1.4 | 1.7e-01 |
| 2026-08-01 | same type | 0.00 | 0.54 | 1.00 | 0.90 | -0.3 | -1.3 | 2.1e-01 |
| 2026-08-09 | street network | 0.00 | 1.58 | 1.27 | 0.97 | -0.6 | +1.9 | 6.2e-02 |
| 2026-08-09 | uniform in city | 0.00 | 1.32 | 1.17 | 0.91 | -0.5 | +1.1 | 2.6e-01 |
| 2026-08-09 | same type | 0.00 | 1.40 | 1.29 | 1.01 | -0.4 | +1.4 | 1.7e-01 |

#### 5.2 Pooled across all five storms, >=0.30 m

Each event's complaints are scored against ITS OWN nearest bookmark,
then pooled. Expected = sum over events of n_event x null rate at
that event's bookmark; z is the normal approximation to the
Poisson-binomial. Spatial clustering is NOT accounted for, so treat
these p-values as an upper bound on confidence.

| complaint type | null | radius | observed | expected | ratio | z | p |
|---|---|---|---|---|---|---|---|
| Water On Street Complaint | street network | 0 m | 36 / 3988 (0.9%) | 35 (0.9%) | **1.04** | +0.2 | 8.1e-01 |
| Water On Street Complaint | street network | 25 m | 781 / 3988 (19.6%) | 522 (13.1%) | **1.50** | +12.4 | 4.7e-35 |
| Water On Street Complaint | street network | 50 m | 1429 / 3988 (35.8%) | 1220 (30.6%) | **1.17** | +7.5 | 8.5e-14 |
| Water On Street Complaint | street network | 100 m | 2424 / 3988 (60.8%) | 2382 (59.7%) | **1.02** | +1.5 | 1.4e-01 |
| Water On Street Complaint | uniform in city | 0 m | 36 / 3988 (0.9%) | 29 (0.7%) | **1.24** | +1.3 | 1.9e-01 |
| Water On Street Complaint | uniform in city | 25 m | 781 / 3988 (19.6%) | 540 (13.5%) | **1.45** | +11.4 | 6.7e-30 |
| Water On Street Complaint | uniform in city | 50 m | 1429 / 3988 (35.8%) | 1248 (31.3%) | **1.15** | +6.4 | 1.2e-10 |
| Water On Street Complaint | uniform in city | 100 m | 2424 / 3988 (60.8%) | 2398 (60.1%) | **1.01** | +0.9 | 3.6e-01 |
| Water On Street Complaint | same type | 0 m | 36 / 3988 (0.9%) | 30 (0.7%) | **1.21** | +1.2 | 2.5e-01 |
| Water On Street Complaint | same type | 25 m | 781 / 3988 (19.6%) | 619 (15.5%) | **1.26** | +7.2 | 5.3e-13 |
| Water On Street Complaint | same type | 50 m | 1429 / 3988 (35.8%) | 1336 (33.5%) | **1.07** | +3.2 | 1.2e-03 |
| Water On Street Complaint | same type | 100 m | 2424 / 3988 (60.8%) | 2442 (61.2%) | **0.99** | -0.7 | 5.1e-01 |
| Water in Basement Complaint | street network | 0 m | 25 / 6632 (0.4%) | 70 (1.1%) | **0.36** | -5.4 | 7.3e-08 |
| Water in Basement Complaint | street network | 25 m | 1084 / 6632 (16.3%) | 1034 (15.6%) | **1.05** | +1.7 | 8.9e-02 |
| Water in Basement Complaint | street network | 50 m | 2186 / 6632 (33.0%) | 2379 (35.9%) | **0.92** | -5.0 | 5.5e-07 |
| Water in Basement Complaint | street network | 100 m | 4117 / 6632 (62.1%) | 4528 (68.3%) | **0.91** | -11.2 | 4.3e-29 |
| Water in Basement Complaint | uniform in city | 0 m | 25 / 6632 (0.4%) | 58 (0.9%) | **0.43** | -4.4 | 1.2e-05 |
| Water in Basement Complaint | uniform in city | 25 m | 1084 / 6632 (16.3%) | 1063 (16.0%) | **1.02** | +0.7 | 4.7e-01 |
| Water in Basement Complaint | uniform in city | 50 m | 2186 / 6632 (33.0%) | 2426 (36.6%) | **0.90** | -6.2 | 5.9e-10 |
| Water in Basement Complaint | uniform in city | 100 m | 4117 / 6632 (62.1%) | 4537 (68.4%) | **0.91** | -11.4 | 2.9e-30 |
| Water in Basement Complaint | same type | 0 m | 25 / 6632 (0.4%) | 24 (0.4%) | **1.03** | +0.1 | 8.9e-01 |
| Water in Basement Complaint | same type | 25 m | 1084 / 6632 (16.3%) | 1029 (15.5%) | **1.05** | +1.9 | 6.1e-02 |
| Water in Basement Complaint | same type | 50 m | 2186 / 6632 (33.0%) | 2120 (32.0%) | **1.03** | +1.8 | 7.8e-02 |
| Water in Basement Complaint | same type | 100 m | 4117 / 6632 (62.1%) | 3969 (59.9%) | **1.04** | +3.8 | 1.5e-04 |
| Sewer-related requests | street network | 0 m | 21 / 3253 (0.6%) | 28 (0.9%) | **0.74** | -1.4 | 1.6e-01 |
| Sewer-related requests | street network | 25 m | 599 / 3253 (18.4%) | 429 (13.2%) | **1.39** | +8.9 | 4.6e-19 |
| Sewer-related requests | street network | 50 m | 1148 / 3253 (35.3%) | 1003 (30.8%) | **1.14** | +5.7 | 1.0e-08 |
| Sewer-related requests | street network | 100 m | 1928 / 3253 (59.3%) | 1955 (60.1%) | **0.99** | -1.1 | 2.8e-01 |
| Sewer-related requests | uniform in city | 0 m | 21 / 3253 (0.6%) | 24 (0.7%) | **0.88** | -0.6 | 5.5e-01 |
| Sewer-related requests | uniform in city | 25 m | 599 / 3253 (18.4%) | 444 (13.6%) | **1.35** | +8.1 | 7.6e-16 |
| Sewer-related requests | uniform in city | 50 m | 1148 / 3253 (35.3%) | 1025 (31.5%) | **1.12** | +4.8 | 1.5e-06 |
| Sewer-related requests | uniform in city | 100 m | 1928 / 3253 (59.3%) | 1968 (60.5%) | **0.98** | -1.6 | 1.2e-01 |
| Sewer-related requests | same type | 0 m | 21 / 3253 (0.6%) | 19 (0.6%) | **1.12** | +0.5 | 6.2e-01 |
| Sewer-related requests | same type | 25 m | 599 / 3253 (18.4%) | 473 (14.5%) | **1.27** | +6.4 | 1.9e-10 |
| Sewer-related requests | same type | 50 m | 1148 / 3253 (35.3%) | 997 (30.7%) | **1.15** | +6.0 | 2.4e-09 |
| Sewer-related requests | same type | 100 m | 1928 / 3253 (59.3%) | 1896 (58.3%) | **1.02** | +1.2 | 2.2e-01 |

### 6. Appendix — every bookmark, every point set

Hit rate at 25 m tolerance. `full` is the static max-fill envelope, not
a rain scenario.

**ponded depth >= 0.05 m**

| point set | b70_100yr | b75_100yr | b75_2yr | full | r10 |
|---|---|---|---|---|---|
| `ev|2023-07-02|street` | 98.1% | 98.4% | 97.5% | 99.2% | 92.8% |
| `ev|2020-05-17|street` | 98.5% | 98.5% | 97.7% | 98.5% | 93.5% |
| `ev|2026-07-27|street` | 98.8% | 99.1% | 97.9% | 99.3% | 91.9% |
| `ev|2026-08-01|street` | 98.3% | 98.3% | 97.8% | 98.5% | 92.0% |
| `ev|2026-08-09|street` | 99.3% | 99.4% | 98.7% | 99.8% | 93.0% |
| `ev|2023-07-02|basement` | 99.2% | 99.2% | 98.8% | 99.3% | 93.9% |
| `ev|2020-05-17|basement` | 99.2% | 99.2% | 98.6% | 99.2% | 92.9% |
| `ev|2026-07-27|basement` | 98.2% | 98.2% | 97.7% | 98.2% | 86.0% |
| `ev|2026-08-01|basement` | 98.9% | 98.9% | 97.8% | 98.9% | 91.2% |
| `ev|2026-08-09|basement` | 99.1% | 99.1% | 99.1% | 99.6% | 89.3% |
| `ev|2023-07-02|sewer` | 99.1% | 99.1% | 98.7% | 99.3% | 93.6% |
| `ev|2020-05-17|sewer` | 99.6% | 99.6% | 98.6% | 99.7% | 92.5% |
| `ev|2026-07-27|sewer` | 99.3% | 99.4% | 98.6% | 99.4% | 94.6% |
| `ev|2026-08-01|sewer` | 98.3% | 98.3% | 97.3% | 99.0% | 93.2% |
| `ev|2026-08-09|sewer` | 99.1% | 99.3% | 98.5% | 99.3% | 92.7% |
| `dryday|street` | 97.2% | 97.2% | 96.3% | 97.5% | 91.8% |
| `dryday|basement` | 98.0% | 98.0% | 97.3% | 98.2% | 92.7% |
| `dryday|sewer` | 97.7% | 97.7% | 96.9% | 98.1% | 92.1% |
| `null|street` | 95.0% | 95.2% | 93.6% | 96.6% | 87.0% |
| `null|uniform` | 89.7% | 89.9% | 88.0% | 91.1% | 81.7% |

**ponded depth >= 0.30 m**

| point set | b70_100yr | b75_100yr | b75_2yr | full | r10 |
|---|---|---|---|---|---|
| `ev|2023-07-02|street` | 30.9% | 31.9% | 23.5% | 35.9% | 4.0% |
| `ev|2020-05-17|street` | 29.9% | 30.6% | 21.9% | 33.2% | 2.8% |
| `ev|2026-07-27|street` | 37.6% | 38.2% | 28.4% | 40.4% | 6.4% |
| `ev|2026-08-01|street` | 35.4% | 36.2% | 23.7% | 37.7% | 4.7% |
| `ev|2026-08-09|street` | 35.5% | 35.7% | 27.4% | 37.8% | 4.4% |
| `ev|2023-07-02|basement` | 22.3% | 23.1% | 15.2% | 24.8% | 2.8% |
| `ev|2020-05-17|basement` | 26.2% | 27.2% | 17.7% | 29.5% | 2.3% |
| `ev|2026-07-27|basement` | 39.1% | 42.1% | 24.7% | 46.3% | 4.1% |
| `ev|2026-08-01|basement` | 26.0% | 26.5% | 17.7% | 28.2% | 2.8% |
| `ev|2026-08-09|basement` | 32.9% | 35.1% | 17.8% | 39.1% | 4.0% |
| `ev|2023-07-02|sewer` | 27.7% | 29.2% | 19.3% | 30.8% | 3.1% |
| `ev|2020-05-17|sewer` | 33.9% | 34.6% | 23.4% | 37.8% | 3.8% |
| `ev|2026-07-27|sewer` | 33.9% | 34.4% | 24.9% | 37.6% | 4.0% |
| `ev|2026-08-01|sewer` | 27.1% | 27.7% | 19.5% | 31.8% | 1.4% |
| `ev|2026-08-09|sewer` | 28.9% | 29.6% | 18.1% | 33.3% | 3.5% |
| `dryday|street` | 27.4% | 28.1% | 19.3% | 30.8% | 3.3% |
| `dryday|basement` | 24.2% | 25.0% | 16.4% | 27.3% | 2.1% |
| `dryday|sewer` | 26.4% | 27.1% | 18.1% | 30.1% | 2.5% |
| `null|street` | 25.1% | 25.9% | 16.5% | 31.0% | 2.2% |
| `null|uniform` | 24.8% | 25.6% | 16.9% | 29.7% | 2.7% |

### 7. Point-set bookkeeping

| point set | points | outside raster | outside city | scored |
|---|---|---|---|---|
| `ev|2023-07-02|street` | 644 | 0 | 1 | 643 |
| `ev|2020-05-17|street` | 1456 | 0 | 3 | 1453 |
| `ev|2026-07-27|street` | 949 | 0 | 1 | 948 |
| `ev|2026-08-01|street` | 401 | 0 | 0 | 401 |
| `ev|2026-08-09|street` | 543 | 0 | 0 | 543 |
| `ev|2023-07-02|basement` | 3800 | 0 | 1 | 3799 |
| `ev|2020-05-17|basement` | 1541 | 0 | 0 | 1541 |
| `ev|2026-07-27|basement` | 886 | 0 | 0 | 886 |
| `ev|2026-08-01|basement` | 181 | 0 | 0 | 181 |
| `ev|2026-08-09|basement` | 225 | 0 | 0 | 225 |
| `ev|2023-07-02|sewer` | 455 | 0 | 0 | 455 |
| `ev|2020-05-17|sewer` | 1350 | 0 | 0 | 1350 |
| `ev|2026-07-27|sewer` | 704 | 0 | 1 | 703 |
| `ev|2026-08-01|sewer` | 292 | 0 | 0 | 292 |
| `ev|2026-08-09|sewer` | 453 | 0 | 0 | 453 |
| `dryday|street` | 14085 | 0 | 26 | 14059 |
| `dryday|basement` | 15143 | 0 | 10 | 15133 |
| `dryday|sewer` | 50488 | 0 | 95 | 50393 |
| `null|street` | 100000 | 0 | 881 | 99119 |
| `null|uniform` | 100000 | 0 | 0 | 100000 |


<!-- END GENERATED TABLES -->

---

## v0.4 re-score — curve-number runoff

Re-run 2026-08-19 against `<data_root>/citywide_v04/`, the Phase 1a physics
upgrade: the uniform runoff coefficient C = 0.55 is replaced by a per-cell
NRCS curve number (TR-55) built from NLCD 2021 land cover and imperviousness
and SSURGO hydrologic soil groups. **Everything else is held fixed** — same
five storms, same 3-day windows, same three null models, same seed, same
point sets, same script. Any difference below is the physics.

Provenance note: this document does not add SOURCES entries for v0.4's inputs.
The NLCD 2021 land cover / imperviousness and SSURGO hydrologic soil group
grids were fetched and cited by the Phase 1a work that built the rasters; this
script consumes only the finished depth COGs. **Numbering collision to resolve
on merge:** the 311 / ACIS / street-centerline entries added here are numbered
9-11 in `data/SOURCES.md`, and the physics branch numbers its CN inputs in the
same range.

<!-- BEGIN V04 TABLES -->

<!-- generated by pipeline/validate_311.py — do not hand-edit -->

### A. What changed in the maps

Measured from the rasters themselves, not quoted from the manifests.
"Reachable" = share of a uniform random sample of the city within
25 m of a ponded cell — the null model's own hit rate, i.e. how hard
the map is to beat.

| bookmark | depth | v0.3 wet km2 | v0.4 wet km2 | change | v0.3 reachable | v0.4 reachable |
|---|---|---|---|---|---|---|
| b70_100yr | >=0.05 m | 84.5 (14.1%) | 96.0 (16.0%) | +14% | 89.7% | 90.3% |
| b70_100yr | >=0.30 m | 16.2 (2.7%) | 24.5 (4.1%) | +51% | 24.8% | 27.3% |
| b75_100yr | >=0.05 m | 87.9 (14.7%) | 98.9 (16.5%) | +12% | 89.9% | 90.4% |
| b75_100yr | >=0.30 m | 18.4 (3.1%) | 27.0 (4.5%) | +47% | 25.6% | 27.8% |
| b75_2yr | >=0.05 m | 58.8 (9.8%) | 67.7 (11.3%) | +15% | 88.0% | 88.6% |
| b75_2yr | >=0.30 m | 5.5 (0.9%) | 8.6 (1.4%) | +56% | 16.9% | 20.1% |
| full *(shared)* | >=0.05 m | 109.7 (18.3%) | 109.7 (18.3%) | +0% | 91.1% | 91.1% |
| full *(shared)* | >=0.30 m | 37.5 (6.3%) | 37.5 (6.3%) | +0% | 29.7% | 29.7% |
| r10 | >=0.05 m | 13.7 (2.3%) | 7.7 (1.3%) | -44% | 81.7% | 53.7% |
| r10 | >=0.30 m | 0.3 (0.1%) | 0.2 (0.0%) | -29% | 2.7% | 1.9% |

### B. Headline — pooled over all five storms, >=0.30 m, 25 m tolerance

| complaint type | null | version | observed | expected | ratio [95% CI] | z | p |
|---|---|---|---|---|---|---|---|
| Water On Street Complaint | street network | **v03** | 781 / 3988 (19.6%) | 522 (13.1%) | **1.50** [1.40–1.59] | +12.4 | 4.7e-35 |
| Water On Street Complaint | street network | **v04** | 861 / 3988 (21.6%) | 622 (15.6%) | **1.39** [1.31–1.47] | +10.7 | 9.8e-27 |
| Water On Street Complaint | uniform in city | **v03** | 781 / 3988 (19.6%) | 540 (13.5%) | **1.45** [1.36–1.54] | +11.4 | 6.7e-30 |
| Water On Street Complaint | uniform in city | **v04** | 861 / 3988 (21.6%) | 631 (15.8%) | **1.37** [1.29–1.45] | +10.2 | 1.4e-24 |
| Water On Street Complaint | same type | **v03** | 781 / 3988 (19.6%) | 619 (15.5%) | **1.26** [1.18–1.34] | +7.2 | 5.3e-13 |
| Water On Street Complaint | same type | **v04** | 861 / 3988 (21.6%) | 719 (18.0%) | **1.20** [1.13–1.27] | +6.0 | 1.8e-09 |
| Water in Basement Complaint | street network | **v03** | 1084 / 6632 (16.3%) | 1034 (15.6%) | **1.05** [0.99–1.11] | +1.7 | 8.9e-02 |
| Water in Basement Complaint | street network | **v04** | 1280 / 6632 (19.3%) | 1247 (18.8%) | **1.03** [0.98–1.08] | +1.1 | 2.9e-01 |
| Water in Basement Complaint | uniform in city | **v03** | 1084 / 6632 (16.3%) | 1063 (16.0%) | **1.02** [0.97–1.08] | +0.7 | 4.7e-01 |
| Water in Basement Complaint | uniform in city | **v04** | 1280 / 6632 (19.3%) | 1261 (19.0%) | **1.02** [0.97–1.07] | +0.6 | 5.4e-01 |
| Water in Basement Complaint | same type | **v03** | 1084 / 6632 (16.3%) | 1029 (15.5%) | **1.05** [1.00–1.11] | +1.9 | 6.1e-02 |
| Water in Basement Complaint | same type | **v04** | 1280 / 6632 (19.3%) | 1199 (18.1%) | **1.07** [1.02–1.12] | +2.6 | 9.5e-03 |
| Sewer-related requests | street network | **v03** | 599 / 3253 (18.4%) | 429 (13.2%) | **1.39** [1.30–1.50] | +8.9 | 4.6e-19 |
| Sewer-related requests | street network | **v04** | 691 / 3253 (21.2%) | 512 (15.7%) | **1.35** [1.26–1.44] | +8.8 | 9.4e-19 |
| Sewer-related requests | uniform in city | **v03** | 599 / 3253 (18.4%) | 444 (13.6%) | **1.35** [1.26–1.45] | +8.1 | 7.6e-16 |
| Sewer-related requests | uniform in city | **v04** | 691 / 3253 (21.2%) | 519 (16.0%) | **1.33** [1.25–1.42] | +8.4 | 3.5e-17 |
| Sewer-related requests | same type | **v03** | 599 / 3253 (18.4%) | 473 (14.5%) | **1.27** [1.18–1.36] | +6.4 | 1.9e-10 |
| Sewer-related requests | same type | **v04** | 691 / 3253 (21.2%) | 555 (17.1%) | **1.24** [1.16–1.33] | +6.5 | 8.8e-11 |

⚠ marks a ratio resting on fewer than 30 hits — read the interval, not
the point estimate.

### C. Per storm, water on street, >=0.30 m, 25 m

Against the dry-day null of the same complaint type — the only null that
controls for where 311 calls come from.

| event | total in | bookmark | n | v0.3 hits | v0.3 ratio [95% CI] | v0.4 hits | v0.4 ratio [95% CI] | change |
|---|---|---|---|---|---|---|---|---|
| **Water On Street Complaint** | | | | | | | | |
| 2023-07-02 | 4.01 | b75_2yr | 643 | 151 | **1.22** [1.06–1.39] | 171 | **1.16** [1.02–1.32] | -0.05 |
| 2020-05-17 | 3.39 | b75_2yr | 1453 | 318 | **1.13** [1.03–1.25] | 360 | **1.08** [0.99–1.18] | -0.05 |
| 2026-07-27 | 2.35 | b75_2yr | 948 | 269 | **1.47** [1.33–1.62] | 302 | **1.39** [1.27–1.53] | -0.08 |
| 2026-08-01 | 1.71 | r10 | 401 | 19 | **1.43** [0.92–2.20] ⚠ | 14 | **1.47** [0.88–2.42] ⚠ | +0.04 |
| 2026-08-09 | 1.03 | r10 | 543 | 24 | **1.33** [0.90–1.96] ⚠ | 14 | **1.08** [0.65–1.80] ⚠ | -0.25 |
| *pooled* | | | 3988 | 781 | **1.26** [1.18–1.34] | 861 | **1.20** [1.13–1.27] | -0.06 |
| **Water in Basement Complaint** | | | | | | | | |
| 2023-07-02 | 4.01 | b75_2yr | 3799 | 579 | **0.93** [0.86–1.00] | 686 | **0.94** [0.88–1.01] | +0.01 |
| 2020-05-17 | 3.39 | b75_2yr | 1541 | 272 | **1.08** [0.97–1.20] | 324 | **1.10** [0.99–1.21] | +0.02 |
| 2026-07-27 | 2.35 | b75_2yr | 886 | 219 | **1.51** [1.34–1.69] | 261 | **1.54** [1.38–1.70] | +0.03 |
| 2026-08-01 | 1.71 | r10 | 181 | 5 | **1.30** [0.56–2.97] ⚠ | 4 | **2.01** [0.79–5.05] ⚠ | +0.71 |
| 2026-08-09 | 1.03 | r10 | 225 | 9 | **1.89** [1.00–3.50] ⚠ | 5 | **2.03** [0.87–4.65] ⚠ | +0.14 |
| *pooled* | | | 6632 | 1084 | **1.05** [1.00–1.11] | 1280 | **1.07** [1.02–1.12] | +0.01 |

### D. Did the >=5 cm layer become scoreable?

The v0.3 finding was that at the product's own >=5 cm threshold the map
covers so much of the city that no ratio can move. Same test, both
versions, pooled, 25 m.

| complaint type | version | uniform-null reach @25 m | observed | ratio |
|---|---|---|---|---|
| Water On Street Complaint | v03 | 88.0% | 96.5% | 1.01 |
| Water On Street Complaint | v04 | 88.6% | 90.9% | 1.02 |
| Water in Basement Complaint | v03 | 88.0% | 98.1% | 1.01 |
| Water in Basement Complaint | v04 | 88.6% | 95.7% | 1.01 |

### E. The 1.0 in bookmark, where the footprint moved most

v0.4 shrinks the 1.0 in map hard, so its >=5 cm layer stops saturating:
the dry-day null falls from 91.8% to 65.1% reach. That is a genuinely
more specific map. The question is whether the specificity buys skill,
so here are the only two events that map to that bookmark, at >=5 cm
(where they still have usable counts) against the dry-day null.

| complaint type | event | version | hits / n | rate | null | ratio [95% CI] |
|---|---|---|---|---|---|---|
| Water On Street Complaint | 2026-08-01 | v03 | 369 / 401 | 92.0% | 91.8% | **1.00** [0.97–1.03] |
| Water On Street Complaint | 2026-08-01 | v04 | 263 / 401 | 65.6% | 65.1% | **1.01** [0.93–1.08] |
| Water On Street Complaint | 2026-08-09 | v03 | 505 / 543 | 93.0% | 91.8% | **1.01** [0.99–1.03] |
| Water On Street Complaint | 2026-08-09 | v04 | 371 / 543 | 68.3% | 65.1% | **1.05** [0.99–1.11] |
| Water in Basement Complaint | 2026-08-01 | v03 | 165 / 181 | 91.2% | 92.7% | **0.98** [0.93–1.02] |
| Water in Basement Complaint | 2026-08-01 | v04 | 89 / 181 | 49.2% | 48.4% | **1.02** [0.87–1.16] |
| Water in Basement Complaint | 2026-08-09 | v03 | 201 / 225 | 89.3% | 92.7% | **0.96** [0.91–1.00] |
| Water in Basement Complaint | 2026-08-09 | v04 | 100 / 225 | 44.4% | 48.4% | **0.92** [0.79–1.05] |


<!-- generated by pipeline/validate_311.py — do not hand-edit -->

### 1. Events scored

| event | O'Hare in | Midway in | event total in | citywide gauges (n, min / median / max) | nearest bookmark |
|---|---|---|---|---|---|
| 2023-07-02 | 3.35 | 4.68 | **4.01** | 32, 0.00 / 0.73 / 4.68 | b75_2yr (3.34 in) |
| 2020-05-17 | 3.11 | 3.67 | **3.39** | 37, 0.70 / 1.07 / 3.95 | b75_2yr (3.34 in) |
| 2026-07-27 | 1.76 | 2.94 | **2.35** | 30, 0.00 / 0.00 / 3.31 | b75_2yr (3.34 in) |
| 2026-08-01 | 1.85 | 1.56 | **1.71** | 28, 0.63 / 1.28 / 2.69 | r10 (1.00 in) |
| 2026-08-09 | 1.34 | 0.72 | **1.03** | 33, 0.00 / 0.00 / 2.32 | r10 (1.00 in) |

Event total = mean of the two official NWS climate stations. The gauge
column is every ACIS station in the Chicago bounding box that reported
that day (ASOS + COOP + CoCoRaHS, mixed observation windows) and is
there to show how much a single citywide number hides.

### 2. Complaint volume — the temporal signal

Complaints per day in each event window (event day + 2 days) against
the dry-day rate over 1394 qualifying dry days.

| event | water on street /day | x dry | water in basement /day | x dry | sewer /day | x dry |
|---|---|---|---|---|---|---|
| 2023-07-02 | 214 | **21x** | 1266 | **117x** | 152 | **4x** |
| 2020-05-17 | 484 | **48x** | 514 | **47x** | 450 | **12x** |
| 2026-07-27 | 316 | **31x** | 295 | **27x** | 234 | **6x** |
| 2026-08-01 | 134 | **13x** | 60 | **6x** | 97 | **3x** |
| 2026-08-09 | 181 | **18x** | 75 | **7x** | 151 | **4x** |
| *dry-day baseline* | 10.1 | 1x | 10.9 | 1x | 36.1 | 1x |

### 3. How much of the city each map covers

The reason tolerance radii saturate. "Reachable" = share of a uniform
random sample of the city within that radius of a ponded cell.

| bookmark | depth | wet km2 | % of city | reachable @25 m | @50 m | @100 m |
|---|---|---|---|---|---|---|
| b70_100yr | >=0.05 m | 96.0 | 16.0% | 90.3% | 97.6% | 99.5% |
| b70_100yr | >=0.30 m | 24.5 | 4.1% | 27.3% | 49.5% | 78.4% |
| b75_100yr | >=0.05 m | 98.9 | 16.5% | 90.4% | 97.7% | 99.5% |
| b75_100yr | >=0.30 m | 27.0 | 4.5% | 27.8% | 50.0% | 78.5% |
| b75_2yr | >=0.05 m | 67.7 | 11.3% | 88.6% | 97.2% | 99.4% |
| b75_2yr | >=0.30 m | 8.6 | 1.4% | 20.1% | 42.6% | 74.3% |
| full | >=0.05 m | 109.7 | 18.3% | 91.1% | 97.9% | 99.5% |
| full | >=0.30 m | 37.5 | 6.3% | 29.7% | 51.6% | 79.3% |
| r10 | >=0.05 m | 7.7 | 1.3% | 53.7% | 76.9% | 92.0% |
| r10 | >=0.30 m | 0.2 | 0.0% | 1.9% | 5.8% | 16.7% |

### 4. Hit rates at ponded depth >= 0.05 m

#### Water On Street Complaint

| point set | bookmark | n | 0 m | 25 m | 50 m | 100 m |
|---|---|---|---|---|---|---|
| 2023-07-02 | b75_2yr | 643 | 8.9% | 97.8% | 100.0% | 100.0% |
| 2020-05-17 | b75_2yr | 1453 | 15.5% | 98.2% | 99.9% | 100.0% |
| 2026-07-27 | b75_2yr | 948 | 11.3% | 98.6% | 99.9% | 100.0% |
| 2026-08-01 | r10 | 401 | 0.2% | 65.6% | 83.0% | 94.5% |
| 2026-08-09 | r10 | 543 | 0.9% | 68.3% | 82.0% | 92.4% |
| *null: street network* | r10 | 99119 | 0.6% | 60.7% | 80.1% | 92.9% |
| *null: street network* | b75_2yr | 99119 | 13.5% | 94.2% | 99.3% | 100.0% |
| *null: uniform in city* | r10 | 100000 | 1.3% | 53.7% | 76.9% | 92.0% |
| *null: uniform in city* | b75_2yr | 100000 | 11.3% | 88.6% | 97.2% | 99.4% |
| *null: same type, dry days* | r10 | 14059 | 1.2% | 65.1% | 84.5% | 94.6% |
| *null: same type, dry days* | b75_2yr | 14059 | 9.8% | 96.7% | 99.9% | 100.0% |

#### Water in Basement Complaint

| point set | bookmark | n | 0 m | 25 m | 50 m | 100 m |
|---|---|---|---|---|---|---|
| 2023-07-02 | b75_2yr | 3799 | 4.7% | 99.1% | 100.0% | 100.0% |
| 2020-05-17 | b75_2yr | 1541 | 7.5% | 99.2% | 100.0% | 100.0% |
| 2026-07-27 | b75_2yr | 886 | 7.4% | 98.0% | 100.0% | 100.0% |
| 2026-08-01 | r10 | 181 | 0.6% | 49.2% | 72.4% | 86.7% |
| 2026-08-09 | r10 | 225 | 0.0% | 44.4% | 65.8% | 86.7% |
| *null: street network* | r10 | 99119 | 0.6% | 60.7% | 80.1% | 92.9% |
| *null: street network* | b75_2yr | 99119 | 13.5% | 94.2% | 99.3% | 100.0% |
| *null: uniform in city* | r10 | 100000 | 1.3% | 53.7% | 76.9% | 92.0% |
| *null: uniform in city* | b75_2yr | 100000 | 11.3% | 88.6% | 97.2% | 99.4% |
| *null: same type, dry days* | r10 | 15133 | 0.3% | 48.4% | 73.3% | 90.6% |
| *null: same type, dry days* | b75_2yr | 15133 | 5.9% | 97.6% | 99.9% | 100.0% |

#### Sewer-related requests

| point set | bookmark | n | 0 m | 25 m | 50 m | 100 m |
|---|---|---|---|---|---|---|
| 2023-07-02 | b75_2yr | 455 | 7.9% | 98.9% | 100.0% | 100.0% |
| 2020-05-17 | b75_2yr | 1350 | 12.6% | 99.2% | 99.9% | 100.0% |
| 2026-07-27 | b75_2yr | 703 | 12.4% | 98.9% | 99.9% | 100.0% |
| 2026-08-01 | r10 | 292 | 1.0% | 55.5% | 74.3% | 93.5% |
| 2026-08-09 | r10 | 453 | 1.5% | 58.3% | 77.0% | 90.1% |
| *null: street network* | r10 | 99119 | 0.6% | 60.7% | 80.1% | 92.9% |
| *null: street network* | b75_2yr | 99119 | 13.5% | 94.2% | 99.3% | 100.0% |
| *null: uniform in city* | r10 | 100000 | 1.3% | 53.7% | 76.9% | 92.0% |
| *null: uniform in city* | b75_2yr | 100000 | 11.3% | 88.6% | 97.2% | 99.4% |
| *null: same type, dry days* | r10 | 50393 | 1.1% | 60.8% | 80.4% | 93.0% |
| *null: same type, dry days* | b75_2yr | 50393 | 10.1% | 97.3% | 99.9% | 100.0% |

#### 4.1 Skill at >=0.05 m — event rate / null rate

**Water On Street Complaint**

| event | null | ratio @0 m | ratio @25 m | ratio @50 m | ratio @100 m | z @0 m | z @25 m | p @25 m |
|---|---|---|---|---|---|---|---|---|
| 2023-07-02 | street network | 0.65 | 1.04 | 1.01 | 1.00 | -3.5 | +3.9 | 9.1e-05 |
| 2023-07-02 | uniform in city | 0.78 | 1.10 | 1.03 | 1.01 | -2.0 | +7.3 | 2.3e-13 |
| 2023-07-02 | same type | 0.90 | 1.01 | 1.00 | 1.00 | -0.8 | +1.5 | 1.2e-01 |
| 2020-05-17 | street network | 1.14 | 1.04 | 1.01 | 1.00 | +2.1 | +6.5 | 7.7e-11 |
| 2020-05-17 | uniform in city | 1.37 | 1.11 | 1.03 | 1.01 | +5.0 | +11.5 | 1.9e-30 |
| 2020-05-17 | same type | 1.58 | 1.02 | 1.00 | 1.00 | +6.8 | +3.1 | 1.9e-03 |
| 2026-07-27 | street network | 0.83 | 1.05 | 1.01 | 1.00 | -2.0 | +5.8 | 6.1e-09 |
| 2026-07-27 | uniform in city | 1.00 | 1.11 | 1.03 | 1.01 | -0.0 | +9.7 | 3.8e-22 |
| 2026-07-27 | same type | 1.15 | 1.02 | 1.00 | 1.00 | +1.5 | +3.3 | 1.2e-03 |
| 2026-08-01 | street network | 0.45 | 1.08 | 1.04 | 1.02 | -0.8 | +2.0 | 4.6e-02 |
| 2026-08-01 | uniform in city | 0.19 | 1.22 | 1.08 | 1.03 | -1.9 | +4.8 | 1.9e-06 |
| 2026-08-01 | same type | 0.21 | 1.01 | 0.98 | 1.00 | -1.8 | +0.2 | 8.5e-01 |
| 2026-08-09 | street network | 1.67 | 1.13 | 1.02 | 0.99 | +1.2 | +3.6 | 2.9e-04 |
| 2026-08-09 | uniform in city | 0.70 | 1.27 | 1.07 | 1.00 | -0.8 | +6.8 | 9.4e-12 |
| 2026-08-09 | same type | 0.76 | 1.05 | 0.97 | 0.98 | -0.6 | +1.5 | 1.2e-01 |

**Water in Basement Complaint**

| event | null | ratio @0 m | ratio @25 m | ratio @50 m | ratio @100 m | z @0 m | z @25 m | p @25 m |
|---|---|---|---|---|---|---|---|---|
| 2023-07-02 | street network | 0.35 | 1.05 | 1.01 | 1.00 | -15.8 | +12.7 | 4.6e-37 |
| 2023-07-02 | uniform in city | 0.41 | 1.12 | 1.03 | 1.01 | -12.8 | +20.1 | 3.1e-90 |
| 2023-07-02 | same type | 0.79 | 1.01 | 1.00 | 1.00 | -2.9 | +5.5 | 4.4e-08 |
| 2020-05-17 | street network | 0.56 | 1.05 | 1.01 | 1.00 | -6.9 | +8.3 | 1.1e-16 |
| 2020-05-17 | uniform in city | 0.66 | 1.12 | 1.03 | 1.01 | -4.7 | +13.0 | 1.5e-38 |
| 2020-05-17 | same type | 1.27 | 1.02 | 1.00 | 1.00 | +2.5 | +3.9 | 1.1e-04 |
| 2026-07-27 | street network | 0.55 | 1.04 | 1.01 | 1.00 | -5.3 | +4.8 | 1.8e-06 |
| 2026-07-27 | uniform in city | 0.66 | 1.11 | 1.03 | 1.01 | -3.6 | +8.7 | 2.4e-18 |
| 2026-07-27 | same type | 1.26 | 1.00 | 1.00 | 1.00 | +1.9 | +0.6 | 5.2e-01 |
| 2026-08-01 | street network | 1.00 | 0.81 | 0.90 | 0.93 | +0.0 | -3.2 | 1.5e-03 |
| 2026-08-01 | uniform in city | 0.42 | 0.92 | 0.94 | 0.94 | -0.9 | -1.2 | 2.2e-01 |
| 2026-08-01 | same type | 1.71 | 1.02 | 0.99 | 0.96 | +0.5 | +0.2 | 8.4e-01 |
| 2026-08-09 | street network | 0.00 | 0.73 | 0.82 | 0.93 | -1.1 | -5.0 | 6.0e-07 |
| 2026-08-09 | uniform in city | 0.00 | 0.83 | 0.86 | 0.94 | -1.7 | -2.8 | 5.4e-03 |
| 2026-08-09 | same type | 0.00 | 0.92 | 0.90 | 0.96 | -0.9 | -1.2 | 2.4e-01 |

**Sewer-related requests**

| event | null | ratio @0 m | ratio @25 m | ratio @50 m | ratio @100 m | z @0 m | z @25 m | p @25 m |
|---|---|---|---|---|---|---|---|---|
| 2023-07-02 | street network | 0.58 | 1.05 | 1.01 | 1.00 | -3.5 | +4.3 | 1.9e-05 |
| 2023-07-02 | uniform in city | 0.70 | 1.12 | 1.03 | 1.01 | -2.3 | +6.9 | 5.5e-12 |
| 2023-07-02 | same type | 0.78 | 1.02 | 1.00 | 1.00 | -1.6 | +2.1 | 3.4e-02 |
| 2020-05-17 | street network | 0.93 | 1.05 | 1.01 | 1.00 | -1.0 | +7.8 | 5.6e-15 |
| 2020-05-17 | uniform in city | 1.11 | 1.12 | 1.03 | 1.01 | +1.5 | +12.2 | 3.5e-34 |
| 2020-05-17 | same type | 1.24 | 1.02 | 1.00 | 1.00 | +3.0 | +4.3 | 1.9e-05 |
| 2026-07-27 | street network | 0.91 | 1.05 | 1.01 | 1.00 | -0.9 | +5.3 | 1.3e-07 |
| 2026-07-27 | uniform in city | 1.09 | 1.12 | 1.03 | 1.01 | +0.9 | +8.5 | 1.4e-17 |
| 2026-07-27 | same type | 1.22 | 1.02 | 1.00 | 1.00 | +2.0 | +2.6 | 1.0e-02 |
| 2026-08-01 | street network | 1.86 | 0.91 | 0.93 | 1.01 | +1.1 | -1.8 | 6.8e-02 |
| 2026-08-01 | uniform in city | 0.78 | 1.03 | 0.97 | 1.02 | -0.4 | +0.6 | 5.4e-01 |
| 2026-08-01 | same type | 0.95 | 0.91 | 0.92 | 1.01 | -0.1 | -1.9 | 6.3e-02 |
| 2026-08-09 | street network | 2.80 | 0.96 | 0.96 | 0.97 | +2.8 | -1.1 | 2.9e-01 |
| 2026-08-09 | uniform in city | 1.18 | 1.09 | 1.00 | 0.98 | +0.4 | +1.9 | 5.1e-02 |
| 2026-08-09 | same type | 1.42 | 0.96 | 0.96 | 0.97 | +0.9 | -1.1 | 2.7e-01 |

#### 4.2 Pooled across all five storms, >=0.05 m

Each event's complaints are scored against ITS OWN nearest bookmark,
then pooled. Expected = sum over events of n_event x null rate at
that event's bookmark; z is the normal approximation to the
Poisson-binomial. Spatial clustering is NOT accounted for, so treat
these p-values as an upper bound on confidence.

| complaint type | null | radius | observed | expected | ratio | z | p |
|---|---|---|---|---|---|---|---|
| Water On Street Complaint | street network | 0 m | 395 / 3988 (9.9%) | 417 (10.5%) | **0.95** | -1.2 | 2.4e-01 |
| Water On Street Complaint | street network | 25 m | 3625 / 3988 (90.9%) | 3441 (86.3%) | **1.05** | +9.3 | 1.4e-20 |
| Water On Street Complaint | street network | 50 m | 3820 / 3988 (95.8%) | 3779 (94.8%) | **1.01** | +3.1 | 1.8e-03 |
| Water On Street Complaint | street network | 100 m | 3925 / 3988 (98.4%) | 3921 (98.3%) | **1.00** | +0.6 | 5.8e-01 |
| Water On Street Complaint | uniform in city | 0 m | 395 / 3988 (9.9%) | 357 (9.0%) | **1.11** | +2.1 | 3.4e-02 |
| Water On Street Complaint | uniform in city | 25 m | 3625 / 3988 (90.9%) | 3205 (80.4%) | **1.13** | +18.0 | 9.1e-73 |
| Water On Street Complaint | uniform in city | 50 m | 3820 / 3988 (95.8%) | 3684 (92.4%) | **1.04** | +8.6 | 8.2e-18 |
| Water On Street Complaint | uniform in city | 100 m | 3925 / 3988 (98.4%) | 3895 (97.7%) | **1.01** | +3.3 | 1.1e-03 |
| Water On Street Complaint | same type | 0 m | 395 / 3988 (9.9%) | 310 (7.8%) | **1.27** | +5.1 | 4.3e-07 |
| Water On Street Complaint | same type | 25 m | 3625 / 3988 (90.9%) | 3559 (89.2%) | **1.02** | +3.7 | 1.8e-04 |
| Water On Street Complaint | same type | 50 m | 3820 / 3988 (95.8%) | 3837 (96.2%) | **1.00** | -1.5 | 1.3e-01 |
| Water On Street Complaint | same type | 100 m | 3925 / 3988 (98.4%) | 3937 (98.7%) | **1.00** | -1.7 | 8.5e-02 |
| Water in Basement Complaint | street network | 0 m | 361 / 6632 (5.4%) | 846 (12.7%) | **0.43** | -17.9 | 8.7e-72 |
| Water in Basement Complaint | street network | 25 m | 6348 / 6632 (95.7%) | 6112 (92.2%) | **1.04** | +11.3 | 1.6e-29 |
| Water in Basement Complaint | street network | 50 m | 6505 / 6632 (98.1%) | 6509 (98.1%) | **1.00** | -0.4 | 7.1e-01 |
| Water in Basement Complaint | street network | 100 m | 6578 / 6632 (99.2%) | 6602 (99.5%) | **1.00** | -4.5 | 5.8e-06 |
| Water in Basement Complaint | uniform in city | 0 m | 361 / 6632 (5.4%) | 710 (10.7%) | **0.51** | -13.9 | 4.9e-44 |
| Water in Basement Complaint | uniform in city | 25 m | 6348 / 6632 (95.7%) | 5737 (86.5%) | **1.11** | +22.6 | 1.5e-113 |
| Water in Basement Complaint | uniform in city | 50 m | 6505 / 6632 (98.1%) | 6362 (95.9%) | **1.02** | +9.2 | 4.3e-20 |
| Water in Basement Complaint | uniform in city | 100 m | 6578 / 6632 (99.2%) | 6563 (99.0%) | **1.00** | +1.9 | 6.3e-02 |
| Water in Basement Complaint | same type | 0 m | 361 / 6632 (5.4%) | 370 (5.6%) | **0.98** | -0.5 | 6.3e-01 |
| Water in Basement Complaint | same type | 25 m | 6348 / 6632 (95.7%) | 6275 (94.6%) | **1.01** | +4.6 | 3.4e-06 |
| Water in Basement Complaint | same type | 50 m | 6505 / 6632 (98.1%) | 6518 (98.3%) | **1.00** | -1.4 | 1.6e-01 |
| Water in Basement Complaint | same type | 100 m | 6578 / 6632 (99.2%) | 6594 (99.4%) | **1.00** | -2.7 | 6.3e-03 |
| Sewer-related requests | street network | 0 m | 303 / 3253 (9.3%) | 344 (10.6%) | **0.88** | -2.4 | 1.8e-02 |
| Sewer-related requests | street network | 25 m | 2910 / 3253 (89.5%) | 2815 (86.5%) | **1.03** | +5.3 | 9.0e-08 |
| Sewer-related requests | street network | 50 m | 3072 / 3253 (94.4%) | 3088 (94.9%) | **0.99** | -1.3 | 1.8e-01 |
| Sewer-related requests | street network | 100 m | 3189 / 3253 (98.0%) | 3200 (98.4%) | **1.00** | -1.5 | 1.2e-01 |
| Sewer-related requests | uniform in city | 0 m | 303 / 3253 (9.3%) | 294 (9.0%) | **1.03** | +0.6 | 5.7e-01 |
| Sewer-related requests | uniform in city | 25 m | 2910 / 3253 (89.5%) | 2623 (80.6%) | **1.11** | +13.7 | 9.6e-43 |
| Sewer-related requests | uniform in city | 50 m | 3072 / 3253 (94.4%) | 3010 (92.5%) | **1.02** | +4.4 | 1.2e-05 |
| Sewer-related requests | uniform in city | 100 m | 3189 / 3253 (98.0%) | 3179 (97.7%) | **1.00** | +1.2 | 2.1e-01 |
| Sewer-related requests | same type | 0 m | 303 / 3253 (9.3%) | 262 (8.1%) | **1.16** | +2.7 | 7.7e-03 |
| Sewer-related requests | same type | 25 m | 2910 / 3253 (89.5%) | 2893 (88.9%) | **1.01** | +1.1 | 2.7e-01 |
| Sewer-related requests | same type | 50 m | 3072 / 3253 (94.4%) | 3104 (95.4%) | **0.99** | -2.9 | 3.8e-03 |
| Sewer-related requests | same type | 100 m | 3189 / 3253 (98.0%) | 3201 (98.4%) | **1.00** | -1.7 | 8.8e-02 |

### 5. Hit rates at ponded depth >= 0.30 m

#### Water On Street Complaint

| point set | bookmark | n | 0 m | 25 m | 50 m | 100 m |
|---|---|---|---|---|---|---|
| 2023-07-02 | b75_2yr | 643 | 1.2% | 26.6% | 49.1% | 75.1% |
| 2020-05-17 | b75_2yr | 1453 | 1.7% | 24.8% | 43.8% | 71.5% |
| 2026-07-27 | b75_2yr | 948 | 2.3% | 31.9% | 52.5% | 77.2% |
| 2026-08-01 | r10 | 401 | 0.0% | 3.5% | 7.2% | 16.5% |
| 2026-08-09 | r10 | 543 | 0.0% | 2.6% | 8.5% | 18.8% |
| *null: street network* | r10 | 99119 | 0.1% | 1.6% | 5.3% | 15.1% |
| *null: street network* | b75_2yr | 99119 | 1.7% | 19.9% | 42.1% | 74.5% |
| *null: uniform in city* | r10 | 100000 | 0.0% | 1.9% | 5.8% | 16.7% |
| *null: uniform in city* | b75_2yr | 100000 | 1.4% | 20.1% | 42.6% | 74.3% |
| *null: same type, dry days* | r10 | 14059 | 0.0% | 2.4% | 6.8% | 17.9% |
| *null: same type, dry days* | b75_2yr | 14059 | 1.5% | 22.9% | 45.2% | 75.1% |

#### Water in Basement Complaint

| point set | bookmark | n | 0 m | 25 m | 50 m | 100 m |
|---|---|---|---|---|---|---|
| 2023-07-02 | b75_2yr | 3799 | 0.4% | 18.1% | 35.0% | 65.8% |
| 2020-05-17 | b75_2yr | 1541 | 0.6% | 21.0% | 37.3% | 67.7% |
| 2026-07-27 | b75_2yr | 886 | 1.4% | 29.5% | 49.4% | 76.2% |
| 2026-08-01 | r10 | 181 | 0.0% | 2.2% | 6.6% | 11.6% |
| 2026-08-09 | r10 | 225 | 0.0% | 2.2% | 6.2% | 12.9% |
| *null: street network* | r10 | 99119 | 0.1% | 1.6% | 5.3% | 15.1% |
| *null: street network* | b75_2yr | 99119 | 1.7% | 19.9% | 42.1% | 74.5% |
| *null: uniform in city* | r10 | 100000 | 0.0% | 1.9% | 5.8% | 16.7% |
| *null: uniform in city* | b75_2yr | 100000 | 1.4% | 20.1% | 42.6% | 74.3% |
| *null: same type, dry days* | r10 | 15133 | 0.0% | 1.1% | 2.9% | 8.6% |
| *null: same type, dry days* | b75_2yr | 15133 | 0.6% | 19.2% | 37.3% | 65.6% |

#### Sewer-related requests

| point set | bookmark | n | 0 m | 25 m | 50 m | 100 m |
|---|---|---|---|---|---|---|
| 2023-07-02 | b75_2yr | 455 | 1.5% | 23.3% | 42.6% | 67.3% |
| 2020-05-17 | b75_2yr | 1350 | 1.0% | 27.3% | 45.7% | 74.7% |
| 2026-07-27 | b75_2yr | 703 | 1.8% | 29.0% | 50.8% | 75.7% |
| 2026-08-01 | r10 | 292 | 0.0% | 0.7% | 5.1% | 13.4% |
| 2026-08-09 | r10 | 453 | 0.0% | 2.4% | 6.4% | 14.3% |
| *null: street network* | r10 | 99119 | 0.1% | 1.6% | 5.3% | 15.1% |
| *null: street network* | b75_2yr | 99119 | 1.7% | 19.9% | 42.1% | 74.5% |
| *null: uniform in city* | r10 | 100000 | 0.0% | 1.9% | 5.8% | 16.7% |
| *null: uniform in city* | b75_2yr | 100000 | 1.4% | 20.1% | 42.6% | 74.3% |
| *null: same type, dry days* | r10 | 50393 | 0.0% | 1.6% | 4.9% | 13.9% |
| *null: same type, dry days* | b75_2yr | 50393 | 1.2% | 21.7% | 41.9% | 72.5% |

#### 5.1 Skill at >=0.30 m — event rate / null rate

**Water On Street Complaint**

| event | null | ratio @0 m | ratio @25 m | ratio @50 m | ratio @100 m | z @0 m | z @25 m | p @25 m |
|---|---|---|---|---|---|---|---|---|
| 2023-07-02 | street network | 0.72 | 1.34 | 1.17 | 1.01 | -0.9 | +4.2 | 2.4e-05 |
| 2023-07-02 | uniform in city | 0.87 | 1.32 | 1.15 | 1.01 | -0.4 | +4.1 | 4.6e-05 |
| 2023-07-02 | same type | 0.83 | 1.16 | 1.09 | 1.00 | -0.5 | +2.2 | 2.9e-02 |
| 2020-05-17 | street network | 1.00 | 1.24 | 1.04 | 0.96 | +0.0 | +4.6 | 4.3e-06 |
| 2020-05-17 | uniform in city | 1.20 | 1.23 | 1.03 | 0.96 | +0.9 | +4.4 | 1.2e-05 |
| 2020-05-17 | same type | 1.15 | 1.08 | 0.97 | 0.95 | +0.7 | +1.6 | 1.0e-01 |
| 2026-07-27 | street network | 1.35 | 1.60 | 1.25 | 1.04 | +1.4 | +9.1 | 6.2e-20 |
| 2026-07-27 | uniform in city | 1.61 | 1.58 | 1.23 | 1.04 | +2.3 | +8.9 | 3.6e-19 |
| 2026-07-27 | same type | 1.55 | 1.39 | 1.16 | 1.03 | +2.0 | +6.3 | 2.6e-10 |
| 2026-08-01 | street network | 0.00 | 2.17 | 1.38 | 1.09 | -0.4 | +3.0 | 2.9e-03 |
| 2026-08-01 | uniform in city | 0.00 | 1.84 | 1.25 | 0.98 | -0.4 | +2.3 | 2.0e-02 |
| 2026-08-01 | same type | 0.00 | 1.47 | 1.06 | 0.92 | -0.4 | +1.4 | 1.5e-01 |
| 2026-08-09 | street network | 0.00 | 1.60 | 1.61 | 1.24 | -0.5 | +1.8 | 7.5e-02 |
| 2026-08-09 | uniform in city | 0.00 | 1.36 | 1.46 | 1.12 | -0.5 | +1.1 | 2.5e-01 |
| 2026-08-09 | same type | 0.00 | 1.08 | 1.25 | 1.05 | -0.4 | +0.3 | 7.7e-01 |

**Water in Basement Complaint**

| event | null | ratio @0 m | ratio @25 m | ratio @50 m | ratio @100 m | z @0 m | z @25 m | p @25 m |
|---|---|---|---|---|---|---|---|---|
| 2023-07-02 | street network | 0.23 | 0.91 | 0.83 | 0.88 | -6.2 | -2.8 | 4.8e-03 |
| 2023-07-02 | uniform in city | 0.27 | 0.90 | 0.82 | 0.89 | -5.4 | -3.1 | 1.8e-03 |
| 2023-07-02 | same type | 0.61 | 0.94 | 0.94 | 1.00 | -1.8 | -1.6 | 1.1e-01 |
| 2020-05-17 | street network | 0.34 | 1.06 | 0.89 | 0.91 | -3.4 | +1.1 | 2.8e-01 |
| 2020-05-17 | uniform in city | 0.41 | 1.04 | 0.88 | 0.91 | -2.8 | +0.9 | 3.8e-01 |
| 2020-05-17 | same type | 0.90 | 1.10 | 1.00 | 1.03 | -0.3 | +1.7 | 8.2e-02 |
| 2026-07-27 | street network | 0.79 | 1.48 | 1.17 | 1.02 | -0.8 | +7.1 | 1.6e-12 |
| 2026-07-27 | uniform in city | 0.94 | 1.46 | 1.16 | 1.03 | -0.2 | +6.9 | 5.7e-12 |
| 2026-07-27 | same type | 2.09 | 1.54 | 1.33 | 1.16 | +2.5 | +7.5 | 8.6e-14 |
| 2026-08-01 | street network | 0.00 | 1.37 | 1.26 | 0.77 | -0.3 | +0.6 | 5.2e-01 |
| 2026-08-01 | uniform in city | 0.00 | 1.16 | 1.14 | 0.69 | -0.3 | +0.3 | 7.6e-01 |
| 2026-08-01 | same type | 0.00 | 2.01 | 2.30 | 1.36 | -0.1 | +1.4 | 1.6e-01 |
| 2026-08-09 | street network | 0.00 | 1.38 | 1.18 | 0.85 | -0.3 | +0.7 | 4.7e-01 |
| 2026-08-09 | uniform in city | 0.00 | 1.17 | 1.07 | 0.77 | -0.3 | +0.4 | 7.3e-01 |
| 2026-08-09 | same type | 0.00 | 2.03 | 2.15 | 1.51 | -0.1 | +1.6 | 1.1e-01 |

**Sewer-related requests**

| event | null | ratio @0 m | ratio @25 m | ratio @50 m | ratio @100 m | z @0 m | z @25 m | p @25 m |
|---|---|---|---|---|---|---|---|---|
| 2023-07-02 | street network | 0.90 | 1.17 | 1.01 | 0.90 | -0.3 | +1.8 | 7.2e-02 |
| 2023-07-02 | uniform in city | 1.07 | 1.16 | 1.00 | 0.91 | +0.2 | +1.7 | 9.2e-02 |
| 2023-07-02 | same type | 1.31 | 1.07 | 1.02 | 0.93 | +0.7 | +0.8 | 4.0e-01 |
| 2020-05-17 | street network | 0.56 | 1.37 | 1.09 | 1.00 | -2.1 | +6.7 | 2.2e-11 |
| 2020-05-17 | uniform in city | 0.67 | 1.35 | 1.07 | 1.01 | -1.5 | +6.5 | 9.0e-11 |
| 2020-05-17 | same type | 0.82 | 1.26 | 1.09 | 1.03 | -0.7 | +4.9 | 9.4e-07 |
| 2026-07-27 | street network | 1.08 | 1.46 | 1.21 | 1.02 | +0.3 | +6.0 | 1.8e-09 |
| 2026-07-27 | uniform in city | 1.29 | 1.44 | 1.19 | 1.02 | +0.9 | +5.9 | 4.8e-09 |
| 2026-07-27 | same type | 1.57 | 1.34 | 1.21 | 1.04 | +1.6 | +4.7 | 2.8e-06 |
| 2026-08-01 | street network | 0.00 | 0.42 | 0.98 | 0.88 | -0.4 | -1.3 | 2.1e-01 |
| 2026-08-01 | uniform in city | 0.00 | 0.36 | 0.89 | 0.80 | -0.4 | -1.5 | 1.3e-01 |
| 2026-08-01 | same type | 0.00 | 0.43 | 1.04 | 0.96 | -0.2 | -1.2 | 2.2e-01 |
| 2026-08-09 | street network | 0.00 | 1.51 | 1.22 | 0.95 | -0.5 | +1.4 | 1.7e-01 |
| 2026-08-09 | uniform in city | 0.00 | 1.28 | 1.10 | 0.86 | -0.5 | +0.8 | 4.1e-01 |
| 2026-08-09 | same type | 0.00 | 1.54 | 1.29 | 1.03 | -0.3 | +1.4 | 1.5e-01 |

#### 5.2 Pooled across all five storms, >=0.30 m

Each event's complaints are scored against ITS OWN nearest bookmark,
then pooled. Expected = sum over events of n_event x null rate at
that event's bookmark; z is the normal approximation to the
Poisson-binomial. Spatial clustering is NOT accounted for, so treat
these p-values as an upper bound on confidence.

| complaint type | null | radius | observed | expected | ratio | z | p |
|---|---|---|---|---|---|---|---|
| Water On Street Complaint | street network | 0 m | 55 / 3988 (1.4%) | 53 (1.3%) | **1.04** | +0.3 | 7.6e-01 |
| Water On Street Complaint | street network | 25 m | 861 / 3988 (21.6%) | 622 (15.6%) | **1.39** | +10.7 | 9.8e-27 |
| Water On Street Complaint | street network | 50 m | 1525 / 3988 (38.2%) | 1332 (33.4%) | **1.15** | +6.9 | 5.7e-12 |
| Water On Street Complaint | street network | 100 m | 2422 / 3988 (60.7%) | 2411 (60.5%) | **1.00** | +0.4 | 6.8e-01 |
| Water On Street Complaint | uniform in city | 0 m | 55 / 3988 (1.4%) | 44 (1.1%) | **1.25** | +1.6 | 1.0e-01 |
| Water On Street Complaint | uniform in city | 25 m | 861 / 3988 (21.6%) | 631 (15.8%) | **1.37** | +10.2 | 1.4e-24 |
| Water On Street Complaint | uniform in city | 50 m | 1525 / 3988 (38.2%) | 1351 (33.9%) | **1.13** | +6.2 | 7.6e-10 |
| Water On Street Complaint | uniform in city | 100 m | 2422 / 3988 (60.7%) | 2419 (60.6%) | **1.00** | +0.1 | 9.0e-01 |
| Water On Street Complaint | same type | 0 m | 55 / 3988 (1.4%) | 46 (1.2%) | **1.20** | +1.3 | 1.8e-01 |
| Water On Street Complaint | same type | 25 m | 861 / 3988 (21.6%) | 719 (18.0%) | **1.20** | +6.0 | 1.8e-09 |
| Water On Street Complaint | same type | 50 m | 1525 / 3988 (38.2%) | 1441 (36.1%) | **1.06** | +2.9 | 3.2e-03 |
| Water On Street Complaint | same type | 100 m | 2422 / 3988 (60.7%) | 2455 (61.6%) | **0.99** | -1.2 | 2.1e-01 |
| Water in Basement Complaint | street network | 0 m | 36 / 6632 (0.5%) | 107 (1.6%) | **0.34** | -6.9 | 4.1e-12 |
| Water in Basement Complaint | street network | 25 m | 1280 / 6632 (19.3%) | 1247 (18.8%) | **1.03** | +1.1 | 2.9e-01 |
| Water in Basement Complaint | street network | 50 m | 2369 / 6632 (35.7%) | 2643 (39.9%) | **0.90** | -7.0 | 2.6e-12 |
| Water in Basement Complaint | street network | 100 m | 4269 / 6632 (64.4%) | 4701 (70.9%) | **0.91** | -12.3 | 1.0e-34 |
| Water in Basement Complaint | uniform in city | 0 m | 36 / 6632 (0.5%) | 90 (1.4%) | **0.40** | -5.7 | 1.1e-08 |
| Water in Basement Complaint | uniform in city | 25 m | 1280 / 6632 (19.3%) | 1261 (19.0%) | **1.02** | +0.6 | 5.4e-01 |
| Water in Basement Complaint | uniform in city | 50 m | 2369 / 6632 (35.7%) | 2676 (40.3%) | **0.89** | -7.8 | 6.1e-15 |
| Water in Basement Complaint | uniform in city | 100 m | 4269 / 6632 (64.4%) | 4692 (70.7%) | **0.91** | -12.0 | 4.6e-33 |
| Water in Basement Complaint | same type | 0 m | 36 / 6632 (0.5%) | 40 (0.6%) | **0.89** | -0.7 | 4.9e-01 |
| Water in Basement Complaint | same type | 25 m | 1280 / 6632 (19.3%) | 1199 (18.1%) | **1.07** | +2.6 | 9.5e-03 |
| Water in Basement Complaint | same type | 50 m | 2369 / 6632 (35.7%) | 2332 (35.2%) | **1.02** | +1.0 | 3.3e-01 |
| Water in Basement Complaint | same type | 100 m | 4269 / 6632 (64.4%) | 4116 (62.1%) | **1.04** | +4.0 | 5.7e-05 |
| Sewer-related requests | street network | 0 m | 33 / 3253 (1.0%) | 43 (1.3%) | **0.76** | -1.6 | 1.1e-01 |
| Sewer-related requests | street network | 25 m | 691 / 3253 (21.2%) | 512 (15.7%) | **1.35** | +8.8 | 9.4e-19 |
| Sewer-related requests | street network | 50 m | 1212 / 3253 (37.3%) | 1095 (33.7%) | **1.11** | +4.6 | 4.7e-06 |
| Sewer-related requests | street network | 100 m | 1951 / 3253 (60.0%) | 1982 (60.9%) | **0.98** | -1.3 | 2.0e-01 |
| Sewer-related requests | uniform in city | 0 m | 33 / 3253 (1.0%) | 36 (1.1%) | **0.91** | -0.6 | 5.7e-01 |
| Sewer-related requests | uniform in city | 25 m | 691 / 3253 (21.2%) | 519 (16.0%) | **1.33** | +8.4 | 3.5e-17 |
| Sewer-related requests | uniform in city | 50 m | 1212 / 3253 (37.3%) | 1112 (34.2%) | **1.09** | +3.9 | 8.5e-05 |
| Sewer-related requests | uniform in city | 100 m | 1951 / 3253 (60.0%) | 1987 (61.1%) | **0.98** | -1.5 | 1.3e-01 |
| Sewer-related requests | same type | 0 m | 33 / 3253 (1.0%) | 30 (0.9%) | **1.11** | +0.6 | 5.4e-01 |
| Sewer-related requests | same type | 25 m | 691 / 3253 (21.2%) | 555 (17.1%) | **1.24** | +6.5 | 8.8e-11 |
| Sewer-related requests | same type | 50 m | 1212 / 3253 (37.3%) | 1089 (33.5%) | **1.11** | +4.9 | 1.2e-06 |
| Sewer-related requests | same type | 100 m | 1951 / 3253 (60.0%) | 1923 (59.1%) | **1.01** | +1.2 | 2.4e-01 |

### 6. Appendix — every bookmark, every point set

Hit rate at 25 m tolerance. `full` is the static max-fill envelope, not
a rain scenario.

**ponded depth >= 0.05 m**

| point set | b70_100yr | b75_100yr | b75_2yr | full | r10 |
|---|---|---|---|---|---|
| `ev|2023-07-02|street` | 98.6% | 98.6% | 97.8% | 99.2% | 67.3% |
| `ev|2020-05-17|street` | 98.5% | 98.5% | 98.2% | 98.5% | 63.7% |
| `ev|2026-07-27|street` | 99.1% | 99.2% | 98.6% | 99.3% | 66.1% |
| `ev|2026-08-01|street` | 98.5% | 98.5% | 97.8% | 98.5% | 65.6% |
| `ev|2026-08-09|street` | 99.4% | 99.6% | 98.7% | 99.8% | 68.3% |
| `ev|2023-07-02|basement` | 99.2% | 99.2% | 99.1% | 99.3% | 60.4% |
| `ev|2020-05-17|basement` | 99.2% | 99.2% | 99.2% | 99.2% | 45.8% |
| `ev|2026-07-27|basement` | 98.2% | 98.2% | 98.0% | 98.2% | 45.3% |
| `ev|2026-08-01|basement` | 98.9% | 98.9% | 97.8% | 98.9% | 49.2% |
| `ev|2026-08-09|basement` | 99.6% | 99.6% | 99.1% | 99.6% | 44.4% |
| `ev|2023-07-02|sewer` | 99.1% | 99.1% | 98.9% | 99.3% | 60.4% |
| `ev|2020-05-17|sewer` | 99.6% | 99.6% | 99.2% | 99.7% | 55.5% |
| `ev|2026-07-27|sewer` | 99.4% | 99.4% | 98.9% | 99.4% | 65.9% |
| `ev|2026-08-01|sewer` | 98.6% | 98.6% | 97.9% | 99.0% | 55.5% |
| `ev|2026-08-09|sewer` | 99.3% | 99.3% | 99.1% | 99.3% | 58.3% |
| `dryday|street` | 97.4% | 97.4% | 96.7% | 97.5% | 65.1% |
| `dryday|basement` | 98.1% | 98.1% | 97.6% | 98.2% | 48.4% |
| `dryday|sewer` | 97.9% | 97.9% | 97.3% | 98.1% | 60.8% |
| `null|street` | 95.5% | 95.6% | 94.2% | 96.6% | 60.7% |
| `null|uniform` | 90.3% | 90.4% | 88.6% | 91.1% | 53.7% |

**ponded depth >= 0.30 m**

| point set | b70_100yr | b75_100yr | b75_2yr | full | r10 |
|---|---|---|---|---|---|
| `ev|2023-07-02|street` | 34.1% | 34.4% | 26.6% | 35.9% | 2.0% |
| `ev|2020-05-17|street` | 32.5% | 32.6% | 24.8% | 33.2% | 1.8% |
| `ev|2026-07-27|street` | 39.8% | 40.0% | 31.9% | 40.4% | 5.2% |
| `ev|2026-08-01|street` | 36.9% | 37.2% | 29.9% | 37.7% | 3.5% |
| `ev|2026-08-09|street` | 36.6% | 37.4% | 31.3% | 37.8% | 2.6% |
| `ev|2023-07-02|basement` | 24.3% | 24.6% | 18.1% | 24.8% | 0.8% |
| `ev|2020-05-17|basement` | 29.1% | 29.2% | 21.0% | 29.5% | 1.2% |
| `ev|2026-07-27|basement` | 45.1% | 45.8% | 29.5% | 46.3% | 1.7% |
| `ev|2026-08-01|basement` | 27.1% | 27.6% | 19.9% | 28.2% | 2.2% |
| `ev|2026-08-09|basement` | 37.3% | 38.7% | 23.1% | 39.1% | 2.2% |
| `ev|2023-07-02|sewer` | 29.2% | 30.3% | 23.3% | 30.8% | 1.8% |
| `ev|2020-05-17|sewer` | 36.7% | 37.0% | 27.3% | 37.8% | 2.2% |
| `ev|2026-07-27|sewer` | 36.3% | 36.8% | 29.0% | 37.6% | 2.3% |
| `ev|2026-08-01|sewer` | 29.5% | 30.1% | 23.3% | 31.8% | 0.7% |
| `ev|2026-08-09|sewer` | 31.8% | 32.2% | 24.1% | 33.3% | 2.4% |
| `dryday|street` | 29.3% | 29.9% | 22.9% | 30.8% | 2.4% |
| `dryday|basement` | 26.2% | 26.7% | 19.2% | 27.3% | 1.1% |
| `dryday|sewer` | 28.5% | 29.0% | 21.7% | 30.1% | 1.6% |
| `null|street` | 27.8% | 28.4% | 19.9% | 31.0% | 1.6% |
| `null|uniform` | 27.3% | 27.8% | 20.1% | 29.7% | 1.9% |

### 7. Point-set bookkeeping

| point set | points | outside raster | outside city | scored |
|---|---|---|---|---|
| `ev|2023-07-02|street` | 644 | 0 | 1 | 643 |
| `ev|2020-05-17|street` | 1456 | 0 | 3 | 1453 |
| `ev|2026-07-27|street` | 949 | 0 | 1 | 948 |
| `ev|2026-08-01|street` | 401 | 0 | 0 | 401 |
| `ev|2026-08-09|street` | 543 | 0 | 0 | 543 |
| `ev|2023-07-02|basement` | 3800 | 0 | 1 | 3799 |
| `ev|2020-05-17|basement` | 1541 | 0 | 0 | 1541 |
| `ev|2026-07-27|basement` | 886 | 0 | 0 | 886 |
| `ev|2026-08-01|basement` | 181 | 0 | 0 | 181 |
| `ev|2026-08-09|basement` | 225 | 0 | 0 | 225 |
| `ev|2023-07-02|sewer` | 455 | 0 | 0 | 455 |
| `ev|2020-05-17|sewer` | 1350 | 0 | 0 | 1350 |
| `ev|2026-07-27|sewer` | 704 | 0 | 1 | 703 |
| `ev|2026-08-01|sewer` | 292 | 0 | 0 | 292 |
| `ev|2026-08-09|sewer` | 453 | 0 | 0 | 453 |
| `dryday|street` | 14085 | 0 | 26 | 14059 |
| `dryday|basement` | 15143 | 0 | 10 | 15133 |
| `dryday|sewer` | 50488 | 0 | 95 | 50393 |
| `null|street` | 100000 | 0 | 881 | 99119 |
| `null|uniform` | 100000 | 0 | 0 | 100000 |


<!-- END V04 TABLES -->

### Verdict on v0.4: better physics, no better skill

**The curve-number upgrade does not beat the baseline. On the primary metric
it is very slightly worse.**

| water on street, ≥30 cm, 25 m, pooled | v0.3 | v0.4 |
|---|---|---|
| vs. dry-day null (the honest one) | **1.26** [1.18–1.34] | **1.20** [1.13–1.27] |
| vs. street-network null | 1.50 [1.40–1.59] | 1.39 [1.31–1.47] |
| vs. uniform null | 1.45 [1.36–1.54] | 1.37 [1.29–1.45] |

The intervals overlap heavily, so this is **not** a demonstrated degradation —
it is a demonstrated *absence of improvement*. The direction is consistent
though: all three nulls move the same way, and the three storms with usable
counts each drop (−0.05, −0.05, −0.08).

**Why, mechanically.** v0.4 found *more* water in the right places — the
observed hit rate rose from 19.6% to 21.6%. But it found more water
everywhere: the ≥30 cm design-storm footprints grew 47-56%, so the null rose
faster, 15.5% → 18.0%. Skill is the ratio, and the denominator won. A model
that wets more of the city is not more informative unless the extra wetness is
where the complaints are, and here it was not.

**The 1.0 in bookmark went the other way and it still did not help.** v0.4
shrinks that map hard (−44% at ≥5 cm, −29% at ≥30 cm), which is a real gain in
specificity — the dry-day null's reach at ≥5 cm falls from 91.8% to 65.1%, so
that layer finally stops saturating. But the ratio stays at 1.00-1.05
(Section E). A much more selective map picked out the complaint locations no
better than the loose one did. That is the most informative single result in
this re-score: **the problem is not that the footprint was too big. It is that
the footprint, at any size, is not preferentially where people report water.**

**Basements: still no skill.** 1.05 → 1.07. The pooled z crosses the
conventional threshold (p = 0.0095 against p = 0.061), and that must not be
read as v0.4 giving the model basement skill. It is a 7% effect, the p-value
is an upper bound that ignores spatial clustering, and the largest storm in
the set is still *below* 1 (0.94). The scope boundary is unchanged: this
project says nothing about basements.

**Counts got too thin at the low end, exactly as expected.** The two August
2026 events map to the 1.0 in bookmark, whose ≥30 cm footprint is now 0.2 km²
— 0.04% of the city. Their hit counts fell from 19 and 24 to **14 and 14** for
street, and from 5 and 9 to **4 and 5** for basements. Every one of those
ratios now has a confidence interval spanning 1.0 (e.g. 1.47 [0.88-2.42]).
**They carry no information and are marked ⚠ in every table.** The pooled
figure is dominated by the three larger storms, which is the right place for
the weight to sit, but it means this re-score effectively rests on three
events, not five.

**What would have counted as success.** A ratio above 1.26 against the dry-day
null, or the same ratio achieved with a materially smaller footprint. v0.4
delivered neither: the footprint grew where the events are and the ratio fell.

**What this does not say.** It does not say curve-number runoff is wrong.
CN is a citable standard and uniform C = 0.55 was an admitted guess; v0.4 is
better-founded physics and better-founded physics is worth having on its own
terms. It says the 311 test cannot detect the improvement — plausibly because
the binding constraint is elsewhere: the drainage term D is still uniform, the
sewer network is still absent, rainfall is still uniform citywide, and the DEM
is still 2016. Any of those could dominate the residual.

---

## Reading the numbers

### 1. The complaint types are genuinely rain-driven

Section 2 is not a test of the model — it is a sanity check that the test is
pointed at the right thing, and it passes overwhelmingly. Water-in-basement
complaints ran at **117×** the dry-day rate in the 2023-07-02 window;
water-on-street peaked at **48×** on 2020-05-17. Even the smallest event
scored, 1.03 in, produced 18× the dry-day street rate.

So there is a real, enormous signal in *when* these complaints happen. The
question this document actually asks is whether the model knows *where*, and
that is a much harder question with a much weaker answer.

### 2. At ≥5 cm the metric saturates and measures nothing

Section 3 is the diagnosis. At ≥5 cm:

| bookmark | wet | within 25 m of wet | within 100 m |
|---|---|---|---|
| 1.0 in | 2.3% of the city | 81.7% | 99.1% |
| 3.34 in | 9.8% | 88.0% | 99.4% |
| max fill | 18.3% | 91.1% | 99.5% |

A map you can reach from 88% of the city by walking 25 m is not screening
anything. Consequently every ≥5 cm ratio at 25 m or wider sits between 1.00
and 1.14 — and several of those are "statistically significant" at z > 18
purely because n is large. **Significance is not skill.** The
water-in-basement figure of 1.12 against the uniform null carries a p-value of
1e-147; it is still a 12% effect against a null that was never plausible.

At ≥30 cm the same maps cover 0.1% (1.0 in) to 6.3% (max fill) of the city and
the test starts working.

### 3. Water on street, ≥30 cm: the one real result

Pooled over all five storms, at 25 m:

| null | observed | expected | ratio | z | p |
|---|---|---|---|---|---|
| street network | 19.6% | 13.1% | **1.50** | +12.4 | 5e-35 |
| uniform in city | 19.6% | 13.5% | **1.45** | +11.4 | 7e-30 |
| **dry-day, same type** | 19.6% | 15.5% | **1.26** | +7.2 | 5e-13 |

Per event, against the dry-day null, the ratio is 1.22, 1.13, 1.47, 1.43 and
1.33 — every one above 1, which is worth more than any single p-value. The
direction is consistent across five independent storms spanning 1.0 to 4.0 in.

The gap between the geometric nulls (1.45-1.50) and the dry-day null (1.26) is
itself the lesson: roughly *half* of the model's apparent skill against a
random-points baseline is just the fact that 311 calls come from where people
live and drive. That half is not the model's.

### 4. Water in basement: no skill, correctly

Pooled ratio against the dry-day null: **1.05**, z = +1.9, p = 0.06. Against
the geometric nulls at 50 and 100 m it is actually *below* 1 (0.90-0.92) —
basement complaints are, if anything, slightly further from modelled ponding
than a random street point is.

This is the model behaving honestly. `docs/METHOD.md` has always said there
are no sewers in it. Basement flooding in Chicago is overwhelmingly combined-
sewer surcharge pushing back up a floor drain, and that is a function of pipe
capacity and antecedent conditions, not of a depression in the ground surface.

The practical consequence is a labelling requirement: **nothing in this
project may be presented as saying anything about basements.**

### 5. Exact-cell (0 m) tests are biased against address geocodes

At ≥5 cm, water-in-basement complaints hit the exact modelled cell at 4.4%
against a street-network null of 11.0% — a ratio of 0.40, z = −17.3. Read
naively that says the model is worse than random. It is an artefact:

- 311 geocodes land on building addresses, and the DEM is **bare earth**, so
  the surface under an address is an interpolation across a removed building.
  Depressions do not survive that.
- The street-network null, by construction, samples the crown-and-gutter
  geometry where real depressions are.

The tell is that against the **dry-day** null — which shares the geocoding
convention exactly — the same ratio is 1.03. The null did its job. This is why
0 m is reported but never used as the headline.

### 6. 100 m tolerance is worthless

Every pooled 100 m ratio, at both thresholds and against all three nulls,
falls between 0.91 and 1.04. At ≥5 cm, 99.9% of everything hits. At ≥30 cm
the null itself is 60-72%.
A 100 m tolerance in a city on a 60 m alley grid means "somewhere on this
block or the next one". Do not quote 100 m numbers.

25 m is the only radius that is both forgiving enough for block-level geocodes
and tight enough to discriminate.

### 7. The design-storm bookmarks are untested — and untestable this way

The largest two-station event in the whole 311 era is **4.01 in** (2023-07-02).
The two bookmarks the project's design-storm story rests on — Bulletin 70's
7.58 in and Bulletin 75's 8.57 in — have **no observational analogue** in the
record. Nothing in this document validates them. They are extrapolations of a
model that has only ever been checked at the bottom of its range.

Every event scored here mapped to either the 1.0 in or the 3.34 in bookmark.

### 8. One rain number for the whole city is the biggest simplification

The scenario model applies a single rain depth citywide, so the observation it
is scored against has to be a single number too. The cost of that is visible
in Section 1: on 2026-07-27 the gauges inside the city bounding box ranged
from **0.00 to 3.31 in**. On 2023-07-02 they ranged 0.00 to 4.68, and the
storm's true core sat over the West Side and the near-west suburbs, well above
either climate station.

And the skill ratios line up with that. Ordered by event total, the
water-on-street ratio against the dry-day null goes:

| event total | 4.01 in | 3.39 in | 2.35 in | 1.71 in | 1.03 in |
|---|---|---|---|---|---|
| skill ratio | 1.22 | **1.13** | **1.47** | 1.43 | 1.33 |

**The two largest storms score worst.** That is the opposite of what you would
want from a tool meant to help before a big storm, and it is consistent with
the uniform-rain simplification: the bigger the storm, the more convective and
spatially concentrated it was, and the worse a single citywide depth describes
it. 2020-05-17, the weakest of the five, also had 3.5 in of rain three days
earlier — antecedent wetness the model has no term for.

The caveat on reading too much into this: these are five points, and the
per-event ratios carry wide intervals (the 1.43 and 1.33 rest on 19 and 24
hits). The ordering is a hypothesis worth testing with more events, not an
established relationship.

---

## Where the model fails, specifically

1. **Basements. Entirely.** Ratio 1.05, not significant. Not a defect — a
   scope boundary — but it must be said out loud wherever the map is shown.
2. **At its own ≥5 cm threshold it is an envelope, not a screen.** It cannot
   be scored, and by extension cannot usefully rank blocks, at that depth.
3. **At the low end it has almost nothing to point at.** The 1.0 in bookmark's
   ≥30 cm footprint is 0.3 km², 0.1% of the city. The 2026-08-01 and
   2026-08-09 windows produced 401 and 543 street complaints; the model
   located 19 and 24 of them. The ratios (1.43, 1.33) rest on those two-digit
   counts and should not be over-read.
4. **The nearest-bookmark mapping is crude.** 1.71 in was scored against the
   1.0 in map — a 40% understatement. Phase 1b's ladder of ~12 rungs is the
   fix, and this exercise is direct evidence it is needed.
5. **Uniform rain against non-uniform storms.** Skill is *lowest* for the two
   largest events scored (§8) — the wrong direction for a tool whose purpose
   is to be useful before a big storm.
6. **No antecedent conditions.** 2020-05-17 followed 3.5 in three days
   earlier; the model treats every event as landing on the same dry ground.
7. **2016 lidar.** Ten years of regrading, new detention, and construction are
   invisible to a DEM flown in 2016, and the complaints run to 2026.

---

## Caveats on the statistics

- **Spatial autocorrelation is not accounted for.** Complaints cluster; so do
  ponds. Every p-value here treats points as independent, which they are not.
  Read them as an **upper bound on confidence**. The consistency of the
  direction across five storms is stronger evidence than any single p.
- **Duplicate SRs are retained** (24-29% of street records in event windows),
  which inflates effective clustering further.
- **Dry days skew seasonal.** 1,394 rain-free days include winter, so the
  dry-day null carries snowmelt and water-main-break street water. That is
  still "street water not caused by a storm", which is the right control, but
  it is not a perfectly matched one.
- **Observation windows differ.** ASOS daily totals are midnight-to-midnight
  local; the CoCoRaHS gauges in the spread column read at 7 am. The event-day
  windows are calendar days in America/Chicago.
- **The event window is 3 days** (event day + 2). Complaints trickle in after
  a storm; a shorter window loses real reports, a longer one picks up
  unrelated ones. 3 days was chosen a priori and not tuned.
- **No temporal holdout.** These five storms are the ones that exist; the
  model was not fitted to them, but neither is this an out-of-sample test in
  any formal sense.

---

## What this changes

For the roadmap:

- **Phase 1a has been scored and did not move the needle** (1.26 → 1.20
  against the dry-day null). Keep the curve-number physics — it is citable and
  defensible where uniform C = 0.55 was not — but stop treating runoff as the
  binding constraint. The remaining uniform terms are the drainage capacity D,
  the absent sewer network, and citywide-uniform rainfall. Section E argues
  the last of those, or the sewer, is where the residual lives: making the map
  much more *specific* bought no skill at all.
- **Phase 1b's ladder is still worth building**, but for a different reason
  than "accuracy": the nearest-bookmark mapping is what starved the two August
  events (1.71 in scored against a 1.0 in map). A ladder would let those
  events be scored at a rung that matches them, which is a precondition for
  ever having five usable events instead of three.
- **Phase 2's passability work should use ≥30 cm, not ≥5 cm.** The validation
  says that is where the signal lives, independently of the FHWA argument.
  Note v0.4's ≥30 cm design-storm footprints are ~50% larger, so any
  passability count computed on v0.3 will change materially.
- **Phase 4 is still not justified — and v0.4 does not change that.** The gate
  was "a screening tool that has never been scored must not highlight
  forecasts". It has now been scored twice. A ratio of 1.20-1.26 for surface
  ponding, no skill for the flooding people actually call about most, and only
  three of five events carrying usable counts, does not support block-level
  forecast highlighting. Storm Watch, if it ships, must show these numbers on
  the same screen.

---

## Reproducing

```
pipeline/validate_311.py fetch      # caches to <data_root>/validation/
pipeline/validate_311.py score      # writes data/derived/ + the block above
```

Cached inputs (Drive, `<data_root>/validation/`): `sr_flood.ndjson`,
`acis_daily.json`, `acis_event_spread.json`, `street_center_lines.geojson`.
Outputs: `data/derived/validation_311.json` (full machine-readable matrix —
every model version × point set × bookmark × depth × radius, with Wilson
intervals), `data/derived/validation_311_tables.md` (v0.3) and
`data/derived/validation_311_v04_tables.md` (comparison + v0.4). Both table
files are spliced into this document between HTML markers, so the prose and
the numbers cannot drift.

Adding a model version is one entry in `PRODUCTS` at the top of the script:
`(id, subdirectory under <data_root>, label)`. Nothing else changes.

`--refresh` forces a re-pull; without it the cached files are reused and a
re-score reproduces every number exactly (only the `generated` timestamp in
the JSON changes).
