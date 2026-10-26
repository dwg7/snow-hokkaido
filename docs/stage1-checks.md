# Stage-1 checks (2026-10-18)

Checks for task 1 (tile 9/459/186). Sample-based; not exhaustive.

## STAC (Earth Search v1)

Query: bbox 142.73,43.58,143.44,44.09; datetime 2026-09-01..2026-10-18.

| collection | scenes | MGRS tile |
|---|---|---|
| `sentinel-2-l2a` | 25 | 54TXP only |
| `sentinel-2-c1-l2a` | 25 | 54TXP only |
| `sentinel-2-pre-c1-l2a` | 0 | - |

- Both `sentinel-2-l2a` and `sentinel-2-c1-l2a` carry 2026 scenes (same acquisitions, different item IDs). Which one to treat as canonical: **undecided**.
- Assets are COGs on `sentinel-cogs` (us-west-2); `green` (B03), `swir16` (B11), `scl` present.
- Scene bbox of 54TXP covers the stage-1 bbox. The bbox itself is the author's calculation, not independently verified.
- Latest scene at check time: 2026-10-18 (S2C), cloud cover ~1.6% (item metadata, tile-wide).

## bvmap PMTiles `AdmArea`

- Reachable via HTTP range reads; z4-16, MVT, gzip.
- Sampled 18 tiles (12 at z14, 6 at z16) inside the stage-1 area: `AdmArea` has **only `vt_code`** (values seen: 1103, 1104). No municipality code or name attribute.
- `AdmBdry` also has only `vt_code`.
- Consequence: `AdmArea` alone cannot give 5-digit municipality codes. Open: whether 1103/1104 distinguish municipality vs. other area classes; whether `Anno`/`Cntr` names can be joined (not checked).
- Plan per HANDOFF section 4: use MLIT National Land Numerical Information "administrative area" (polygons + 5-digit code) as the source; keep bvmap for cross-checking. Not yet downloaded.

## MLIT National Land Numerical Information, administrative area (N03)

- Source: `https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2026/N03-20260101_01_GML.zip` (Hokkaido, as of 2026-01-01, ~70 MB). Stored under git-ignored `data/raw/`.
- The 2026-04-01 variant does not exist at the probed URL (404); bvmap is dated 2026-04-01, so the two sources differ by 3 months. Impact on Hokkaido boundaries: **unchecked**.
- Fields: `N03_002` (subprefecture), `N03_003` (county), `N03_004` (name), `N03_007` (5-digit code). 9,556 polygon features, JGD2011 (EPSG:6668).
- Features whose bounding box touches the stage-1 bbox (superset; true overlap not yet computed): Kitami 01208, Monbetsu 01219, Oketo 01550, Takinoue 01560, Engaru 01555, Shibetsu 01220, Asahikawa 01204, Kamikawa 01457, Aibetsu 01456, Higashikawa 01458, Biei 01459, Kamishihoro 01633.
- Next: per-municipality overlap with the 512x512 cells, then cellmap.

## obs from one scene (S2C_54TXP_20261018_0_L2A, 2026-10-18 01:35 UTC)

- Result (512x512 cells): **256,767 green, 5,377 snow, 0 cloud/shadow/no-data cells** (a first run that applied the STAC offset to l2a data gave 185,721 snow, wrong; see below). Scene-wide cloud cover per STAC: 1.6%.
- **Reflectance offset (resolved for this scene)**: STAC `raster:bands` says reflectance = DN*0.0001 - 0.1 for both collections, but the files differ. The `sentinel-2-c1-l2a` COGs carry scale 0.0001 / offset -0.1 in their own metadata; the legacy `sentinel-2-l2a` COGs carry none, and their DN is exactly 1000 lower (c1 - l2a = 1000 for every pixel in a 200x200 window of B03 and B11). Applying the STAC offset to l2a data gave ~71% snow in mid-October (wrong). Fix: `make_obs.py` reads scale/offset from each file, not from STAC. With that, both collections give identical classes and clear_pct for 2026-10-18; ndsi_q differs in 7,718 cells (3%, mostly dark cells with ndsi_q ~21), presumably because l2a clips values that c1 keeps (mechanism not verified). One scene and one window checked; older baselines not checked.
- Rules used (provisional, `algo-v1-dev`): NDSI >= 0.42 with no extra reflectance condition; SCL cloud = 8/9/10, shadow = 3, no-data = 0/1, all else clear; B11 bilinear to 10 m; cell = 11x11 pixels (118-128 per cell).
- No hand verification of snow areas against imagery yet.

## events and invariant tests

- `ledger/events/season=2026/part-2026-10-18_s2.parquet`: 12 rows (one per municipality). `just events <obs>` builds it; `just test` runs pytest.
- 4 tests pass: 2 synthetic (random classes with lake/sea/canopy flags; snow/marginal split) and 2 against the ledger (the four invariants; `n_land` equals master `n_land_cells`).
- Provisional rules: marginal = cell-mean NDSI within +/-0.05 of 0.42; `n_clear_canopy` is always 0 (no canopy mask yet, D3); lake/sea cells are excluded from `n_land` but none are flagged in this tile (D4 water source missing).
- Sanity: snow + marginal over all municipalities is 5,565 vs 5,377 class-4 cells in obs; the excess is class-3 cells with NDSI 0.37-0.42 counted as marginal. Not an error, but the totals do not match one-to-one.
- The invariants are largely guaranteed by construction here; they will matter more once canopy/water masks and multiple obs files exist.

## Dashboard (docs/)

- Open MCT 4.3.1 + MapLibre GL JS 5.6.0 (both pinned on unpkg, files confirmed to exist). Tree: root -> MapLibre instrument + three tabularmaps instruments (snow rate, cloud rate, visible rate). Structure follows the cafebabe notes and tabularmaps/do (provider triple, no Telemetry API/Plot/Display Layout).
- Basemap: `https://stars.optgeo.org/style/bvmap-starlight.json` (CORS allowed for localhost; the `/styles/` path 301-redirects to `/style/`). Vendored tabularmaps core: see `docs/vendor/tabularmap/SOURCE.txt`.
- Checked only in the Claude desktop app's embedded browser. Not checked in Chrome/Safari/Firefox, on phones, or on GitHub Pages.
- Rendering quirk: with `raster-resampling: 'nearest'` the class overlay rendered black there; `linear` works. Cause **unconfirmed**. Earlier probes also showed partial alpha / `raster-opacity < 1` rendering dark; the PNG is now opaque (alpha 0/255) and opacity stays 1, so translucency was not re-tested.
- Click on a municipality outline shows the snow rate popup; tabular views have no click-through to a time series yet (single observation only).

## All-Hokkaido cellmap (replaces the stage-1-only cellmap)

- `ledger/grid/cellmap.tif`: one COG mosaic, 7168x4608 z18 cells covering z9 tiles x 454..467, y 183..191 (the N03 extent). 194 codes in `muni/master.parquet` (178 municipalities, 10 Sapporo wards, 6 Northern Territories villages); 6,782,469 land cells (about the 6.7 million estimated in the handoff).
- Same rule as before (cell center inside polygon), done by rasterization. On the stage-1 tile the new mosaic assigns all 262,144 cells to the same municipality as the previous tile-only cellmap.
- Cell area vs polygon area: median |diff| 0.05%, max 0.34% (`docs/muni-area-check.md`). Official areas were not fetched; that check remains open.
- Sapporo: N03 has ten wards and no city code 01100, while the tabularmaps layout uses 01100 (plus a ward expansion); the series export has no Sapporo values yet, so the mapping is **open**.
- `events` now use the full municipality land-cell count as `n_land` (cells outside a pass's footprint are class 0), skip municipalities with no scanned cell, and take several obs files of one pass (`just events <obs> <obs> ...`). `visible_rate` therefore shows coverage for municipalities cut by the tile; `scan_rate` was added.

## Scene cut into z9 tiles; snow rule fix (algo-v1-dev2)

- `just obs <JST date>` now processes every pass of that day: scenes are cut into the land z9 tiles they cover, one file per pass x tile (`obs/season=YYYY/<date>/<datatake_id>/<x>-<y>.tif`), overlapping granules merged by "first by `s2:tile_id` wins". 2026-10-18: one pass, 27 granules, 41 files, about 20 min with 4 parallel jobs, 6.4 MB (`docs/storage.md`).
- Check against the earlier tile-only result on the stage-1 tile (algorithm unchanged at that time): `class` and `clear_pct` identical, `ndsi_q` differs in 62 cells by at most 1 (pixel -> cell mapping now interpolated from a 32-pixel node grid instead of per-pixel projection).
- **False positive found and fixed**: the first full-pass run labelled 68% of the cells in the southern tip tiles as snow in mid-October. Cause: water has high NDSI because B11 is near zero. Snow now also needs B03 reflectance >= 0.10 and SCL != water (6). Effect: southern tip tile 178,874 -> 0 snow cells; stage-1 tile 5,377 -> 5,310. The 0.10 threshold is a rule of thumb (MODIS-style visible-reflectance test), not tuned; dark shadow and shallow/turbid water edge cases are not examined. Diagnosis of the water cause used 6 sample cells, of which 2 read SCL = water and 3 read no-data in the first granule (their value came from another granule of the pass), so it is supported but not exhaustive.
- After the fix, snow above 0.5% of valid cells appears only in Kamikawa, Higashikawa, Biei, Kamifurano and Shintoku (Daisetsuzan / Tokachidake area), plausible for mid-October; not compared with imagery by eye.
- 168 municipalities are touched by that pass; 13 of them are only partly covered (`scan_rate` < 100%).

## Display layer prototype: raster PMTiles per JST date (observed mode)

- `just view-tiles <date>` writes `docs/data/view/obs-<date>.pmtiles` and `dates.json`. A z18 cell is exactly one z10 pixel (152.87 m), so z10 is the native zoom and z4-z9 are overviews (per 2x2 block: snow > green > cloud > shadow > not scanned); MapLibre overzooms past z10. Palette PNG tiles, alpha 0/255 only.
- 2026-10-18: 224 tiles, **0.41 MB** (z10 about 289 KB). Test `tests/test_view_tiles.py` checks that the z10 pixels equal the obs cells of tile 9/459/186 (alignment) and the overview priority rule.
- Dashboard: the MapLibre instrument now loads the latest date from `dates.json` through the `pmtiles://` protocol (pmtiles 4.3.0 on unpkg) and starts on the whole of Hokkaido. Seen in the embedded browser: the 2026-10-18 swath, snow along the Daisetsuzan-Tokachidake ridge, aligned with the dashed stage-1 municipality outline. `raster-resampling: 'nearest'` rendered correctly for this tile layer (it did not for the earlier image source); other browsers not checked.
- Preview needs a server that supports HTTP Range (`.claude/launch.json` uses RangeHTTPServer); GitHub Pages and the Source Cooperative data endpoint support it (the latter checked: 206 with `access-control-allow-origin: *`).
- Not built yet: last-known mode (needs `derived/state`), a date slider (only one date exists), municipality outlines for all of Hokkaido, the age palette.
- Daily coverage (STAC, 2026-08-20..10-19, JST days): no day without an acquisition over Hokkaido; 1 datatake on 33 days, 2 on 25, 3 on 3; one day covers 15-77% (median 42%) of the MGRS tiles; per-tile revisit gaps 1/2/3/5 days = 177/681/367/81 cases. Clouds not considered. So observed-mode maps differ every day but cover only part of the island; last-known mode is the full picture.

## Last-known mode, date slider, line work above the raster (prototype)

- `just state <JST date>` (`src/make_state.py`) replays the obs log day by day with `pixel.Folder`, writes `derived/state` rows, `state-<date>.pmtiles` per calendar day and the cell ledger COG (`pixel/`, git-ignored). Check: `n_green + n_snow + n_unknown + n_invalid = n_land` holds for all 194 municipalities x 4 dates (test on synthetic data too). The incremental `Folder` equals the batch `fold` on 20 random sequences.
- Data actually replayed: 2026-10-18 (full pass, 41 tiles) and 2026-10-17 (one pass, only the 3x3 tile block around Daisetsuzan; the full-island run was too slow on a loaded machine, and 2026-10-16 had no scene over that block). State dates 10-17..10-20; ages grow on the days without obs (10-19, 10-20), as designed. Two real observation days are a thin test of the multi-day logic; no real hysteresis case was seen.
- 10-17 over the Daisetsu tile was about 90% cloud (235,556 of 262,144 cells). NDSI snow pixels there agreed with SCL snow only 0.05% (QC tag `qc_ndsi_snow_in_scl_frac`), so the 38 "snow" cells of that day are doubtful (thin cloud edges are a guess, not examined). `qc_flags` does not use this metric yet; it will matter for D8 (hysteresis).
- Dashboard: map instrument has a last-known / observed switch, a date slider over the files in `dates.json`, an age legend (buckets <=1, <=3, <=7, <=14 days, older), and two more tabular instruments (last-known snow rate, freshness). Municipality hover outline and popups were built and then **removed** (see the next section).
- Layer order: the cell raster sits under the basemap water fill and every line layer, so coast, rivers, boundaries, roads and labels are drawn on top; the basemap's topographic area fill is drawn below the raster and its perennial snow (7402) is hidden, because gray snow patches could be mistaken for our data. Verified in the embedded browser only.
- Per-date PMTiles are committed under `docs/data/view/` for now (about 0.3-0.4 MB each); the plan is to keep them on Source Cooperative once the location is decided (`docs/storage.md`).

## Boundary geometry is not published (decision)

- MLIT's N03 page states CC BY 4.0 with attribution, but also shows a Survey Act approval notation for the underlying GSI product; what that means for re-users is not stated there and was not clarified. The owner decided not to seek approval for this small use.
- Removed: `docs/data/muni.geojson` and the map's municipality hover outline and popups (municipality numbers remain on the tabular-map instruments), the unused class PNG, and the `--n03` option of `export_docs.py`. `.gitignore` blocks `docs/data/muni*.geojson`. New: `just fetch-n03`, so each user downloads N03 and builds the cellmap locally.
- **Already in git history, not removed:** `docs/data/muni-stage1.geojson` (a stage-1-tile clip of the boundaries) was merged to `main` through PR #1; `docs/data/muni.geojson` (all Hokkaido, simplified) is in the commits of PR #2's branch on GitHub. **Decision (owner): no history rewrite.** PR #2 is to be merged by squash, so the all-Hokkaido `muni.geojson` never enters `main`'s history (it stays in the branch commits and the PR's refs on GitHub); `muni-stage1.geojson` stays in history through PR #1. Also decided: `ledger/grid/cellmap.tif` and `ledger/muni/master.parquet` (rasterized labels and attributes derived from N03) stay in the repository.

## Northern Territories (Etorofu) coverage check, before the all-Hokkaido run

- cellmap: the six village codes 01695-01700 are present (Shikotan, Tomari, Rubetsu-ya = Kunashir/Shikotan side; Rubetsu 01698, Shana 01699, Shibetoro 01700 = Etorofu). Etorofu cells: 125,704 + 81,469 + 64,628; cell-area sum 3,167.5 km2, matching the island's area (about 3,167 km2; the comparison value is from memory, not fetched). Extent lon 146.86-148.89, lat 44.42-45.56, z9 tiles x 464-467, y 183-185, inside the mosaic (x 454-467, y 183-191); the east edge tile 467 is the last column.
- Sentinel-2: Etorofu lies in UTM zone 55 (MGRS 55T..; EPSG:32655). STAC shows granules there on 13 of the 20 days in Oct 1-20, some days with 100% cloud. `make_obs.py` builds the transforms from each granule's own CRS, so the zone change needs no special case.
- Processing test (2026-10-09, tiles 466/183 and 467/183 only, into a scratch ledger): both tiles produced files; events assigned Shibetoro (01700) 64,628 of 64,628 land cells scanned (cloud 3,775, shadow 2,492, snow 39 + 78 marginal) and Shana (01699) 13,942 of 81,469 (only the part inside the two tiles). Tile 465/184 had no granule in that pass. Snow on the Etorofu volcanoes in early October is plausible; not compared with imagery.
- The basemap (bvmap-starlight tiles) returns content over Etorofu at z6-z12 (checked by tile size, not by eye). The tabular layout and the master agree on the six village codes.
- Found and fixed: the tabular layout has Sapporo as 01100 while N03 has ten wards, so Sapporo showed no data. `export_docs.py` now adds a city row (01100) that sums the wards; the ward rows stay. The city's `age_median` is a cell-weighted mean of the wards' medians (approximate).
- Not checked: one Etorofu tile took 494 s under load (6 granules), so the all-Hokkaido run will be slow where granules of two UTM zones overlap; no run over the whole Etorofu footprint yet.

## Published dashboard (GitHub Pages) and Source Cooperative

- PR #2 was squash-merged into `main` (c960885); the tree has no boundary geometry (`muni-stage1.geojson` remains in the history through PR #1). Pages was already enabled for `main` `/docs` (custom host `dwg7.unopengis.org`); the build of the merge commit succeeded.
- Checked in the Claude desktop app's embedded browser on https://dwg7.unopengis.org/snow-hokkaido/ : the dashboard loads; the map reads `view/dates.json` and the PMTiles from Source Cooperative (HTTP 200/206), the series JSON and plugin from Pages; the last-known snow-rate tabular map renders. Not checked: other browsers, phones, `https://dwg7.github.io/snow-hokkaido/` content (HTTP 200 only), loading time on a slow connection (the first map paint took 20-30 s in one run).
- Upload: `just publish --days 2026-10-17,2026-10-18 --upload` put 14 files (4.5 MB) into `s3://smartmaps/foil4gr1/snow-hokkaido/` with the `source-coop` AWS profile; anonymous range reads and CORS (`*`) were checked on four of the files.

## All-Hokkaido run, 2026-10-01..10-20 (20 JST days)

- `just obs-range 2026-10-20 2026-10-01 --workers 4` finished without errors: 25 passes, 74 MB of tile files in `ledger/obs/`. The first day (10-20, one pass, 32 tile files) took 1,213 s; the whole range took far less than the 7-10 h estimated (the machine was lightly loaded; the total time was not logged). `just rebuild 2026-10-20` then built the events of the 25 passes, the state history 10-01..10-20, the per-day PMTiles (obs and state) and the Pages data; 44 tests pass. `n_green + n_snow + n_unknown + n_invalid = n_land` holds for all 194 municipalities x 20 dates (3,880 rows).
- Share of land cells ever seen clear (last-known coverage): 0.7% (10-01), 25% (10-03), 67% (10-08), 93% (10-10), 99.2% (10-18). Cells last seen as snow: 6 (10-01), about 5,600 (10-05..10-07), 583 (10-10), 316 (10-13), 10,611 (10-18), 1,566 (10-20). Fresh snow in the Daisetsuzan area around 10-17/18 and its quick loss by 10-20 is a reading of these numbers, **not compared with imagery or weather records**; the drop from about 5,200 to 583 between 10-09 and 10-10 coincides with a jump in coverage (67% to 93%), so part of it is simply newly seen cells.
- Etorofu: events exist for Rubetsu (01698), Shana (01699) and Shibetoro (01700) on 11 different days; e.g. 10-04 Shibetoro scanned 100% with 3-4% cloud, 10-09 scanned 100% with 6% cloud and 39 snow cells. Days over Etorofu are often cloudy (cloud 99-100% on 10-11, 10-14, 10-17, 10-19). Coverage by two UTM zones needed no special handling.
- Days with only 3 tile files (10-09, 10-14, 10-19) are passes that touch the east of Hokkaido only.
- Per-date PMTiles are no longer tracked in git (`docs/data/view/` is ignored); they live on Source Cooperative.

## Etorofu on the map (visual check)

- Opened with `?center=148.5,45.3&zoom=9` (new link option of the map instrument) in observed mode, 2026-10-09: the land cells of north-eastern Etorofu (around Shibetoro-dake) follow the coastline of the basemap; the sea stays unpainted; shadow and cloud cells appear as small purple and white patches. A wider view (`?center=147.8,45.0&zoom=8`, last-known mode, 2026-10-20) shows the island's land cells with unknown (transparent) holes where clouds hid the ground on every pass so far. Looked at by eye in the embedded browser only.

## Per-day series for the four rate instruments

- `make_state.py` also writes `derived/daily/season=YYYY.parquet`: for each observed JST day, the events-style counts of that day's observation (one observation per cell per day, the winning pass also supplies `ndsi_q`), 1,437 rows for 20 days. `export_docs.py` turns it into `series/{snow_rate,cloud_rate,visible_rate,scan_rate}_ts.json` (about 20 KB each, 195 codes including the Sapporo city row; `null` where a municipality was not scanned that day). The four tabular instruments got a date slider.
- Definitions match the single-date series (snow rate = `n_snow / n_clear_valid`, which leaves out marginal cells). Spot check: Kamikawa 2026-10-18 gives 2.9% in both the per-pass series and the per-day series (one pass that day).
- Tests: `tests/test_export_ts.py` (alignment, nulls, Sapporo sum). Looked at in the embedded browser only (the 2026-10-05 view colours the municipalities scanned that day and leaves the rest as no data).
- The two last-known instruments (snow rate, freshness) also have a slider, over every calendar day (21 dates, 2026-10-01..10-21; `series/*_ts.json` from `derived/state`, ages advance on days without observations). Spot check: Kamikawa's last-known snow rate stays at 7.6% from 10-05 to 10-07 (no new clear observation), then 4.7%, 0.0%, and 3.3% on 10-18. Not done: a time-series chart per municipality.

## Date picker (2026-10-22)

The range sliders (map and the six tabular instruments) were replaced by one date picker (`datePicker` in `docs/openmct-plugin.js`), after the Copernicus Browser: ◀ ▶ step to the previous / next date that has data, the date button opens a month calendar in which only dates with data can be chosen, "最新" jumps to the latest, and ← → work when the picker has focus. Checked in the embedded browser: calendar, ◀, date pick on the map; calendar on a tabular instrument (21 selectable days). Two `Cannot read properties of undefined (reading 'key')` promise errors appeared once when switching between instruments; not reproduced on a second switch, cause: no time system selected at start-up (reported by a peer session; `docs/index.html` now sets one). After the fix the error count did not rise on a reload, but the console log may persist across reloads, a fresh tab then showed the error once before the fix and none after it (confirmed). Not checked: other browsers, touch screens, 150+ days of calendar (month navigation is untested with real multi-month data).

## Dashboard shell polish (issue #7, 2026-10-24)

`docs/shell.js` + CSS: browse pane 200 px (inline width set once, a later drag overrides it), inspector collapsed on load (Open MCT's own collapse button; it also writes `hideInspector=true` to the URL), +1 px base font, lighter muted text, user-oriented instrument names (積雪の地図 / 積雪率 / 雲の割合 / 見えた割合 / 撮影できた割合 / 積雪率・最終既知 / 情報の新しさ / 数字と色の作り方), and a viewer mode (`?viewer=1` or the 全画面表示 button) that hides the tree, inspector and header and leaves only the content. Checked in the embedded browser at 1024 px: the map fills the screen in viewer mode and the date picker works there. Not checked: other browsers, phones, the effect of `+1 px` on every Open MCT dialog.

## Animation (2026-10-26)

The date picker has ▶ 再生 / ⏸ 停止, a speed in seconds per day (0.25 to 8; a frame stays that long, default 1) and a repeat box; it plays the whole period in order on the map and on the six tabular instruments (Space toggles it while the picker has focus; picking a date by hand stops it). On the map the next three dates are prefetched as extra raster layers at opacity 0.001 (MapLibre loads no tiles at opacity 0) and shown at opacity 1 only after their tile count has stopped growing for 300 ms, so a slow connection slows the animation instead of flickering. Measured in the embedded browser with the local server: the map advances every 0.6 s at 2 days/s once the buffers are warm (about 5.5 s for the first frame after a cold start), the tabular maps every 0.1 s at 8 days/s. Not checked: the published (remote) tiles, other browsers, phones. The "loaded" test reads MapLibre's internal tile table (`_tiles`, maplibre-gl 5.6.0) because `isSourceLoaded()` never turned true (tiles outside the PMTiles archive stay "loading"); a 5 s cap protects against a library change.

The prefetch depth follows the connection: one date ahead while a date loads faster than 0.8 of a frame, two otherwise (moving average of the measured load time; the wait for a date is capped at 12 s). On the published tiles, at 1 s per day, the map advanced every 1.1-1.2 s (18 frames in 20 s) in the embedded browser; slower connections were not tried. Switching between 最終既知 and 観測値 keeps the date (the same day, or the last earlier day of the other list).

## Loading cue and fade (2026-10-26)

While a requested date is not on screen yet, the map is dimmed with a "読み込み中 <date>" label (after 200 ms, so quick loads do not flash); the legend title keeps showing the date that is actually drawn. A new raster fades in over the old one (150 ms for a single pick; up to half a frame, at most 600 ms, while playing) and the old one is dropped afterwards. Checked in the embedded browser with the published tiles: the dimming and the label appear and clear; partial opacity (0.5) is drawn lighter, not black. The look of the fade itself (smoothness at 0.5-2 s per day) was not judged on screen. Where only one of the two days has data, that area fades in or pops out with the layer.
