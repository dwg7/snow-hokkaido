# Can this architecture run 180 days? (analysis, 2026-10-21)

Two readings of "180 days": (A) **forward**: run the daily update for 180 days; (B) **backfill**: build 180 days of history at once (for example 2026-08-01 .. 2027-01-28, or Oct-Mar). The numbers below mix what was measured on the 21 days of October 2026 (**M**) with extrapolations (**E**). Winter has not been run.

## What was measured (M)

| item | value |
|---|---|
| completeness | for each of the 21 days, the number of pass x tile files equals the STAC plan (21 of 21 days) |
| backfill speed | 19 days (2026-10-01..10-19) in about 254 min with 4 workers: about 13 min per day, about 34 s per file; one real daily run (one pass, 20 files) took 30 min (the machine was busier) |
| local obs (full, with `ndsi_q`) | 592 files, 76.7 MB for 21 days = 3.7 MB per day |
| published (obs-lite, view, events, state) | 50.8 MB for 21 days = 2.4 MB per day |
| state replay | about 1.3 s per day without tile writing, about 3 s per day with all per-day tiles (21 days: 27 s and 61 s) |
| series JSON | about 20 KB per metric for 20 dates |

## Reading A: forward operation for 180 days (works, with two changes)

- Compute per day is constant (about 15-30 min, one to three passes). No growth in the obs step.
- **State replay grows linearly**: today `make_state.py` replays the whole season every run. At 180 days that is about 4 min (replay only) to 9 min (all tiles) per run (E). Acceptable for a PoC; the planned fix is to resume from the saved `pixel` snapshot (`Folder` is incremental already) with a weekly full check.
- **Repository growth**: the six series files change every day (about 1 MB at 180 dates, E). 180 daily commits would add tens of MB. Fix: publish `series/*.json` on Source Cooperative instead of committing them.
- Storage: published about 0.4-0.5 GB, local obs about 0.7 GB (E; snow-covered winter scenes compress worse, perhaps 2x).
- Dashboard: slider with 180 steps and series files of about 180 KB each are fine (E, not tried).

## Reading B: a 180-day backfill (feasible, slow; and risky before the algorithm is settled)

- **Time**: 180 days x 13 min = about 39 h at the measured backfill speed, up to about 90 h at the speed of the one real daily run (E). It is resumable (`just obs-range`), network-bound, and uses about 1.5 GB of memory per worker.
- **Reprocessing cost**: any change to the pixel rule (thresholds, masks) means redoing all of it. The NDSI threshold, the 0.10 B03 floor and the cloud/snow confusion have **not** been checked against imagery. Doing 180 days first and changing the rule later would repeat 40-90 h.
- **Winter is a different regime (not tested)**: Hokkaido winters are cloudy (many passes fully cloud-covered, so last-known ages grow), the sun is low (terrain shadows; December noon elevation at 43 N is about 24 degrees, lower at the morning pass time), frozen lakes and wet snow/cloud confusion in SCL, and sea ice (outside any municipality here, so not counted). The 21 October days already showed one cloudy-day case where NDSI snow disagreed with SCL snow (0.05% agreement on 2026-10-17). D7 (how long old snow/green state is trusted) and D8 (hysteresis) become real questions.
- Summer days (August-September) are snow-free and cost the same compute; skipping them loses only the "green baseline".

## Ways to cut the time (E, none implemented)

1. **Read SCL first, skip B03/B11 where no cell can be clear.** A cell is cloud/shadow/no-data unless more than half of its pixels are clear, and that needs only SCL. For fully cloudy tiles (common in winter) this skips the heavy 10 m reads. Same result by construction; check on the 21 days.
2. Read only the COG blocks of B03/B11 that contain clear pixels.
3. GDAL HTTP settings for range reads (multiplexing, merged ranges); size of the gain not measured.
4. Read B03 from the 20 m overview (4x fewer pixels). Changes results slightly; would need validation against the current 10 m output.
5. Run on a machine in the data's region (us-west-2): much faster I/O, but needs an account and money; not a PoC step.
6. Run two or three days in parallel instead of 4 workers per day (the machine, not the network, becomes the limit).

## Recommendation

1. Forward operation can continue as is; do the incremental state and move the series files before day 60 or so.
2. Before any long backfill: validate the pixel rule on a few scenes (target the cloud/snow confusion and shadows), fix the rule, add `algo_version` to the obs path so old and new runs can sit side by side, implement item 1 above, then backfill newest first (the latest days are the ones people look at).
3. Do the backfill for Oct-Mar (about 150 days) rather than 180 days from August if time matters.

## SCL-first reading: measured effect (2026-10-22)

One granule x tile window with no clear pixel (2026-10-03, tile 9/454/190) took 8.4 s without and 5.1 s with the SCL-first skip; the output was identical. Only one such window turned up in two cloudy days, so the share of skippable windows in winter and the overall saving are **not measured**.
