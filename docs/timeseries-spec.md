# Time-series spec (draft)

Scope: how observations across scenes, tiles and days are keyed, grouped and folded. Extends HANDOFF appendix A; nothing here is implemented beyond `src/pixel.py`.

## 1. Identity

- **The cell `(z18, x, y)` is the only spatial key.** A scene's footprint never defines a ledger unit; it only decides which cells get class != 0.
- Cells outside a scene's footprint are class 0 (not scanned). Denominators (`n_land`) are always the municipality's full land-cell count.
- **Consequence:** `cellmap` must cover every z9 tile that any processed scene touches, and every municipality must have its full cell set before `n_land == master.n_land_cells` holds. Stage 1 satisfies that only because the master counts cells inside the one tile (municipalities cut by the tile edge are partial).

## 2. Unit of storage

- **obs file = one pass x one z9 tile.** A scene is cut into the z9 tiles it intersects.
- **Pass** = `s2:datatake_id`. Checked: 27-28 granules of one overpass share it (Hokkaido, 2026-10-10).
- Overlap between adjacent granules of one pass (MGRS overlap): per cell, take the first granule (sorted by `s2:tile_id`) that scanned it (class != 0). Deterministic; the data in the overlap is the same acquisition.
- **events row = one municipality x one pass**, aggregated over all z9 tiles of that pass (not per file). Key: `event_id = muni_code + pass id hash`.

## 3. De-duplication and reprocessing

- `sentinel-2-l2a` and `sentinel-2-c1-l2a` list the same products under different item IDs (checked for 2026-10-10: identical `s2:product_uri` and `s2:datatake_id`). Dedupe key: `s2:product_uri`. Canonical collection: see section 6 and the decision log.
- A reprocessed product (new `product_uri`, same acquisition) supersedes the old: old events get `superseded_by`; obs files are append-only and kept.
- `algo_version` change = new rows, old rows untouched.

## 4. Day definition

- **Day = JST calendar date of `obs_start_utc`.** (UTC would give the same date for the observed ~01:30 UTC passes; JST matches how users read dates.) Store UTC times; derive the day when folding.
- `day_index = (JST date - season start).days + 1`, season starts Aug 1; `0` means "never".
- Several passes on one day (e.g. S2A and S2B on 2026-10-10) are separate obs/events rows. For the cell ledger they are reduced to **one observation per cell per day**: the latest (by `obs_start_utc`) pass that saw the cell clear (class 3 or 4); cloud/shadow/no-data passes never override a clear one. This avoids same-day ties between "snow" and "green".

## 5. Cell ledger (`pixel`) fold: pure function of the obs log

`fold(obs, upto_day)` uses only obs with `day <= upto_day`, never a previous snapshot. Per cell, over days in ascending order, using the per-day clear observation (section 4):

| field | rule |
|---|---|
| `last_clear_any_day` | last day with a clear observation |
| `last_clear_snow_day` / `last_clear_nosnow_day` | last day with a clear snow / clear no-snow observation |
| `snow_confirm_n` | number of distinct days with a clear snow observation |
| `first_snow_day` | the first of the first two distinct clear-snow days, set once `snow_confirm_n >= 2`; never reset, even by later no-snow days; `0` before that |
| `flags` bit0 (censored) | the cell's first clear observation in the log is snow (no earlier no-snow seen) |

Derived (not stored): state = `snow` if `last_clear_snow_day > last_clear_nosnow_day`, `green` if the reverse, `unknown` if both 0, `invalid` if the cell is masked in `cellmap`. Age = `today - last_clear_any_day`. Equal values cannot happen for a cell with both set (one observation per day).

Properties tested in `tests/test_pixel.py`: order independence of input, prefix property (result at day k ignores later obs), cloud passes change nothing, `first_snow_day` monotonic.

## 6. Reflectance scale/offset

Read scale and offset from each COG's own metadata, never from STAC `raster:bands` (see `stage1-checks.md`: l2a files carry none and are already offset-removed; c1 files carry -0.1). Still worth a per-scene sanity check before a series is trusted: share of negative reflectance in B03 and agreement of NDSI snow with SCL=11 where snow exists. Recorded in obs tags and `qc_flags` bit0 (decided); the threshold needs a few more scenes (2025 and winter) to set.

## 7. Time slider / looking back (what the schema supports, what is missing)

Supported by design:
- `obs` is append-only per pass, so any past date can be rebuilt; `pixel.fold(obs, upto_day=k)` gives the cell state as of day k from the log alone (prefix property tested), with no stored snapshots.
- `events` (municipality x pass) is a per-municipality time series, sorted by (muni_code, obs_start_utc); `derived/state` and `derived/progress` (municipality x date) are specified in HANDOFF appendix A for "as of date" views with age.

Not done yet:
- `derived/state`, `derived/progress`, `derived/series/*.json` and a `latest.json` do not exist; the dashboard shows one observation.
- Per-date view data: the tabularmaps series contract holds one `asOf`. A slider needs either one file per metric and date or one file per metric and season (`{dates: [...], values: {code: [...]}}`). Not designed yet; about 194 values per date per metric is small.
- Per-date map overlay: one class PNG per date is cheap for one z9 tile but not for all of Hokkaido (7168x4608 cells); options are per-z9-tile files, COG range reads, or tiles. Undecided.
- Two modes must stay separate: "observed that day" (events/obs) vs "last known as of that day" (pixel fold, always with age).
- History starts at the first ingested scene. Earlier Sentinel-2 scenes exist in the archive and the fold accepts them, but the censored flag ("first clear observation is snow") depends on where the record starts.

## 8. Last-known products (implemented: `src/make_state.py`)

- `make_state.py --upto <JST date>` replays the obs log from the first day of the season with `pixel.Folder`, one calendar day at a time (days without obs only advance the age). For every day it writes the `derived/state` rows (municipality x date: `n_green`, `n_snow`, `n_unknown`, `n_invalid`, `n_fresh`, `age_median`), the raster PMTiles `state-<date>.pmtiles`, and for the last day the cell ledger as a 6-band uint16 COG (`pixel/season=YYYY/<date>.tif`, a git-ignored cache). Invariant tested: `n_green + n_snow + n_unknown + n_invalid = n_land`.
- Display palette index per cell: 0 transparent (never seen clear, or masked), 1-5 green and 6-10 snow, each from fresh to old. **Age buckets (proposal, provisional): <=1, <=3, <=7, <=14 days, older.** Reason: typical revisit gaps are 2-3 days with 5 at most (STAC, Aug-Oct 2026), so the first buckets mean "seen at the last or the one before pass"; clouds stretch the real gap. `n_fresh` uses 7 days (D7, provisional).
- Overviews take the highest rank per 2x2 block: snow > green, fresher > older.
- Not decided: whether old snow/green should expire to "unknown" after some days (D7); for now it never expires, it only fades.

## Decision log

| item | status |
|---|---|
| Day = JST date | decided (no VIIRS planned, so no cross-midnight products) |
| Pass = `s2:datatake_id` | decided; verified shared by 27-28 granules of one pass (Hokkaido, 2026-10-10) |
| Dedupe key = `s2:product_uri` | decided; identical in both collections |
| Canonical collection | decided: `sentinel-2-c1-l2a` (file metadata carries the offset, keeps dark pixels); both gave identical classes on the one scene tested |
| Offset check record | decided: metrics in obs tags (`qc_neg_b03_frac`, `qc_ndsi_snow_in_scl_frac`) and `qc_flags` bit0 on events; threshold 0.25 for the negative B03 share is provisional |

## Not decided here

D2 (VIIRS counting), D3/D4 (canopy, water masks), D7 (carry-over days N), D8 (hysteresis).

**Decision (2026-10-26, owner): D7.** Not decided now; it is decided when it is needed. If it is, N = 60 days (measured on the 2025 season: a 60-day limit would turn only 0-5% of the last-known cells into "unknown"; 30 days would turn 10-30%). It is a display/semantics rule; it would not make rebuilds noticeably faster (the cost is reading imagery, not replaying the state).
