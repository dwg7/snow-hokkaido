# Where the obs data lives (estimate and options)

## Measured

- One pass over Hokkaido, 2026-10-18 (one datatake, 41 land z9 tiles): **41 files, 6.4 MB in total, mean 155 KB, max 214 KB** per pass x tile file (deflate COG, three uint8 bands).
- Per band, on the stage-1 tile: `ndsi_q` about 75% of the bytes, `class` and `clear_pct` a few KB each. A random-noise `class` band would cost about 48 KB, so cloudy or patchy-snow days may be larger. Winter scenes have **not** been measured.
- Speed: about 50-70 s per tile job (network-bound), 4 jobs in parallel, about 20 min for the 41-file pass on one laptop.
- STAC count for the stage-1 area: 25 items between Sep 1 and Oct 18 (about 0.5 per day, about 190 per year, including same-day duplicates of different passes).

- Display layer (class only, raster PMTiles z4-z10) for the same pass: **0.41 MB** per date; the same mosaic as one COG with overviews: 0.29 MB; with `ndsi_q` added: 7.4 MB. So `ndsi_q` is what makes obs large; the map does not need it.

## Extrapolation (assumptions: about 190 acquisitions per tile per year, 62 land tiles, 155 KB per file)

| item | per year |
|---|---|
| obs files | about 11,800 |
| obs size | about 1.8 GB (plausible range 1.5-3 GB; winter unmeasured) |
| events (194 municipalities x about 190 passes) | about 37,000 rows, a few MB of Parquet (not measured) |
| display layer, observed mode (one PMTiles per date) | about 190 x 0.4 MB = about 80 MB |
| pixel cache (latest snapshot only) | tens of MB (not measured) |

Rebuilding a year of obs from the public archive at the measured speed would take about 63 hours (190 passes x 20 min), so a copy is worth keeping, but loss is not fatal: obs is derived from public data (the offset story shows the archive can be reprocessed, which is the argument for keeping our own copy).

## Options (facts about services are my understanding, not verified unless stated)

| option | fit | notes |
|---|---|---|
| In git | no | repository policy (no large data) and size; about 2 GB/year |
| Git LFS | no | free quotas are small compared with this volume |
| GitHub Releases (one archive per month) | backup only | per-file limit about 2 GB; no HTTP range reads of single tiles |
| Source Cooperative | candidate | named in the handoff; the site responds (checked); upload terms, limits and auth **not checked**; needs an account that the owner must create |
| Own S3-compatible bucket (e.g. R2) | candidate | needs an account and keys from the owner; costs not checked |
| Local disk only | interim | `ledger/obs/` stays git-ignored; nothing is shared |

Range reads matter for the dashboard only if it reads obs directly; the current pages need only light derived files (series JSON, one class PNG).

## Decision (owner, after this report)

- **Destination:** Source Cooperative, folder `snow-hokkaido/` in the owner's `smartmaps/foil4gr1` repository (the owner's account). Upload tool and exact endpoint conventions are **not verified**; `just publish` is a dry run by default and prints the `aws s3 sync` command it would run (`--upload` to execute, with credentials already in the environment).
- **obs:** the light version, one COG per pass (class + clear_pct on the whole cellmap extent, about 1 MB per pass; measured 0.54 / 0.97 MB for two passes). `ndsi_q` stays local.
- **pixel:** the latest snapshot only (`pixel/season=YYYY/latest.tif`); past states are replayed from the obs-lite files (`pixel.fold`), and per-day `state-<date>.pmtiles` keep the cell-level state and age bucket of each day.
- **Not published:** municipality boundary geometry and anything rasterized from it (`grid/cellmap.tif`, `muni/master.parquet`); users build them with `just fetch-n03` and `just cellmap`. The repository tracking of those two files is undecided.
- Dry run on the current ledger: 13 files, 4.5 MB (obs 1.5, view 1.6, pixel 1.3, events/derived 0.05).
