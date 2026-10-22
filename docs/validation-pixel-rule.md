# Pixel rule check against imagery (2026-10-21)

Rule under test (`algo-v1-dev2`): a pixel is snow when it is clear (not SCL cloud 8/9/10, shadow 3, no data 0/1), `NDSI >= 0.42`, `B03 reflectance >= 0.10` and SCL is not water; a cell is a clear class when more than half of its pixels are clear.

Method: four 5-8 km windows read from the same COGs, shown as four panels left to right: true colour (TCI), our classes (blue snow, green no snow, lavender cloud, purple shadow), NDSI (grey), SCL (cyan = snow/ice, light grey = cloud classes, brown = bare/dark, tan = not vegetated). Looked at by eye; **there is no ground truth** (no station or weather data was used), so "agrees" means agrees with what the image shows and with SCL. Images contain modified Copernicus Sentinel data 2026.

## Findings

| window | what the image shows | result |
|---|---|---|
| Daisetsuzan, 2026-10-18, clear (cloud 2%) | large snow field above the forest line, snow filling the stream channels below | the blue area follows the white area and the channels closely. 96.6% of rule-snow pixels are also SCL snow (404,797 of 419,108); SCL marks about 15% more pixels as snow than the rule does (mixed edge pixels). Snow count changes only -/+6% for NDSI 0.30..0.50, and not at all with the B03 floor: robust on a clear day |
| Shibetoro-dake, Etorofu, 2026-10-09, clear (cloud 1%) | small snow patches near the summit; cloud and cloud shadow elsewhere | 1,142 of 1,377 rule-snow pixels are SCL snow (83%); count changes by about 4% between NDSI 0.36 and 0.50 |
| Kurodake side, 2026-10-17, broken cloud over snowy ridges | thick cloud with ridge snow showing at the cloud edge | the rule marks 2,480 pixels as snow, SCL marks 4. **46% of them are within 3 px (30 m) of SCL cloud, 73% within 10 px**; their SCL classes are dark area (2), unclassified (7) and not vegetated (5), their B03 is bright (median 0.61, NDSI 0.48): probably real snow seen through thin cloud or at cloud edges, but not reliable. The count is **threshold sensitive**: 2,480 at NDSI 0.42, 971 at 0.50, 95 at 0.60 |
| north of Daisetsu, 2026-10-17, almost fully cloudy | cloud | 1,536 rule-snow pixels of only 2,828 clear pixels; 60% within 3 px of cloud; SCL marks none. Doubtful |
| Daisetsu, 2026-10-17, fully cloudy | cloud | all cloud, no false snow (13 snow pixels of 640,000) |

Whole ledger (21 days, 592 tile files): 26,039 snow cells; 6.0% have `clear_pct < 80` and 8.7% `< 90`. On the clear day 2026-10-18 it is 5 of 10,287; on cloudy days it is large (2026-10-03: 30%, 10-16: 19%, 10-21: 90% of that day's few snow cells).

## What this says

1. On clear days the rule is robust and matches the imagery and SCL. The B03 floor (0.10) does nothing there; it matters only for water, where it was needed.
2. The weak spot is **cloud edges and thin cloud**: snow cells with partial clear pixels, on days with much cloud. Those are the cells that can flip the last-known state wrongly.
3. Not checked: terrain shadow on snow in winter (SCL class 2 contained real shaded snow on 10-18, so excluding it would hurt), frozen lakes, wet snow, low-sun scenes, anything in December-March.

## Decision: applied as `algo-v1-dev3` (owner approved, 2026-10-22)

- Keep NDSI 0.42 and the B03 floor.
- **A cell becomes class snow only if at least 80% of its pixels are clear** (`clear_pct >= 80`); otherwise the cell is treated as not observed (cloud class). Effect on the existing 21 days: 1,569 of 26,039 snow cells (6%) would change, almost all on cloudy days; 0 of 10,287 on 2026-10-18.
- A pixel-level cloud buffer (exclude snow within about 3 px of cloud) removes a similar set but costs more compute; the cell-level rule is cheaper and uses fields already stored (`clear_pct`).
- Because `clear_pct` is stored in `obs`, the 21 existing days can be re-derived without reading imagery again; only a new `algo_version` and new obs files are needed (obs is append-only).

### Applied

- `src/make_obs.py`: `SNOW_MIN_CLEAR_PCT = 80`; a snow-majority cell below it falls through to "not seen" (most frequent of no data / cloud / shadow). Tag `snow_min_clear_pct`.
- The 21 existing days were re-derived by `src/migrate_obs_rule.py` without re-reading imagery: 592 files, **1,569 snow cells set to class 1** (the same number as predicted). The old files do not keep the per-class counts of the other pixels, so the dropped cells are all "cloud"; a rebuild from imagery (`just obs <date> --force`) can pick shadow or no data instead. Files carry `migrated_from=algo-v1-dev2`. Events, state, daily, display tiles and series were rebuilt; 48 tests pass.
- Not changed: NDSI 0.42, B03 floor, the pass/day logic. Still unchecked: winter (December-March), ground truth.

## SCL-first reading (speed)

`process_granule` reads SCL (20 m) before B03/B11; when no pixel of the window is clear, B03/B11 are not read (`SCL_FIRST`). Results are unchanged in the cases compared (identical `cls`, `ndsi_q`, `clear_pct` in 8 granule x tile pairs with clear pixels; see `docs/scaling-180d.md` for the time effect on cloud-only windows).
