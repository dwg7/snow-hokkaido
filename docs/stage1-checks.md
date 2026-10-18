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
