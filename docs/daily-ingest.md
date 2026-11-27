# Daily ingest (in operation since 2026-10-27; the design notes below are kept, the current setup is in the last two sections)

Goal: every day, pick up new Sentinel-2 passes over Hokkaido, extend the ledger and the published files, with no manual steps except what cannot be automated (see "Open questions"). Everything below reuses what exists: `make_obs.py` (resumable), `make_events.py`, `make_state.py`, `make_view_tiles.py`, `publish.py`.

## What one run does

1. **Discover.** STAC search (c1-l2a, Hokkaido bbox) for the last `LOOKBACK` JST days (default 3). Group by `s2:datatake_id`, de-duplicate by `s2:product_uri` (already done in `day_items`). Granules of one pass reach Earth Search over several hours, and Sentinel-2 L2A appears with a delay (not measured here), so a run looks back instead of only at "yesterday".
2. **Build obs.** For each pass x land z9 tile of those days: skip when the file exists **and** its `product_uri` tag already lists every granule STAC now shows for that tile; otherwise rebuild (today's rule "file exists, skip" would miss granules that arrive later; this needs a small change).
3. **Events.** One file per pass (`part-<JST date>_<datatake>.parquet`); rewrite it when any of its tiles was rebuilt (same `event_id`; the old file is replaced, not appended).
4. **State.** `make_state.py` replays the whole season (about 8 s per calendar day, measured on 3-4 days; a full season would take about 50 min, **estimated**). Better: resume from the cached `pixel` snapshot of the last day already processed and feed only new days, with a full replay once a week as a check that both agree (`Folder` is already incremental; the snapshot reader is not written).
5. **View files.** `obs-<date>` and `state-<date>` PMTiles only for the dates that changed; then `dates.json` last.
6. **Publish.** `just publish --upload` style sync to Source Cooperative, data first, `view/dates.json` last, no `--delete`.

## Where the files live (so a run needs no git commit)

- Per-day products already live on Source Cooperative. The small `series/*.json` files that the tabular instruments read are still served from the repository (`docs/data/series/`), so every run would need a commit and a Pages rebuild. **Proposal:** publish `series/*.json` next to `view/` on Source Cooperative and let the dashboard read them from the same base (a few lines in the plugin). Then only code changes go through pull requests.

## When and where it runs (open)

- Overpasses over Hokkaido are around 01:00-01:40 UTC (10:00-10:40 JST). L2A availability on Earth Search was not measured; a first run in the evening JST and a second the next morning would cover late items (the lookback makes a second run harmless).
- A full day of passes took about 20 min (one pass, 32 tiles) when the machine was idle; two or three passes per day mean up to about an hour. Memory per worker about 1.5 GB.
- Candidates: (a) the owner's machine via launchd/cron, with the existing `source-coop` AWS profile; (b) a scheduled agent task in the Claude app; (c) GitHub Actions (free for public repos, 6 h job limit) if a non-interactive upload credential exists.

## Open questions for the owner

1. **Credentials.** `source-coop login` produced cached credentials that had expired again within a day or so; an unattended upload needs a long-lived key or a refresh that does not need a browser. Not known whether Source Cooperative offers one. Until then: processing can run unattended, upload stays a manual `just publish --upload` after login.
2. Where to run it (a, b or c above).
3. Notification on failure (e-mail, the Claude app, an issue).

## Failure handling

- Every step is idempotent (skip-complete, replace-by-key), so a failed run is simply run again.
- STAC or S3 outages: the run exits non-zero after retries; nothing is published (`dates.json` is last).
- A partially written COG is detected by opening it (done in `make_obs.py`); a partial upload is repaired by the next sync.
- Reprocessed products (new `product_uri` for the same acquisition) supersede the old ones: rebuild the tile, keep the old event file marked `superseded_by` (not implemented).

## Order of work

1. late-granule refresh in `make_obs.py`; 2. `just daily` (steps 1-5, dry-run publish); 3. incremental state from the `pixel` snapshot with the weekly full check; 4. move `series/*.json` to Source Cooperative; 5. scheduler and notification once the credential question is settled.

## Status (2026-11-28)

- Implemented and running: late-granule refresh, `just daily`, `series/*.json` and `stage1.json` on Source Cooperative, the launchd job and `scripts/run-daily.sh`, the macOS notification.
- Not implemented: resuming the state from the cached `pixel` snapshot, `superseded_by`.

## Decisions (owner, 2026-10-26) and what is set up

- **Where:** the owner's Mac, a per-user launchd job (`scripts/install-launchd.sh`) that runs `scripts/run-daily.sh` **every day at 02:00 JST**. Yesterday's passes (about 10:00 JST) have been in STAC for hours by then, and the 3-day lookback picks up late granules.
- **What it does:** fast-forwards the code, runs `just daily` (obs, events, state, tiles, series, and a staged copy of the upload), logs to `<run dir>/logs/daily-<date>.log` and writes `logs/last-run.txt`. It makes **no git commits** (events and derived tables are untracked caches; the series files and `stage1.json` are published next to `view/`) and **does not upload**.
- **Upload:** still a manual `source-coop login` + `just publish --upload` (the login lasts about a day and needs a browser). No API-key option was found; not checked beyond that. When the published data are 3 or more days behind, the job shows a macOS notification as a reminder.
- **Failure:** a macOS notification with the log path; the run is idempotent, so running it again repairs it. One run at a time (a lock; stale after 6 h).
- **Run dir:** `~/snow-hokkaido-run`, a clone of the repository holding the ledger data (obs, pixel, events, derived, tiles, staging). It is separate from the Claude worktrees so that cleaning those cannot remove the data.
- **Sleep:** launchd runs a missed 02:00 job after the Mac wakes. To wake the Mac for it: `sudo pmset repeat wakeorpoweron MTWRFSU 01:55:00` (needs the owner's password; not done here).
- **Sleep makes a run slow, not wrong:** the Mac wakes for a few seconds (DarkWake) and sleeps again, so the job is suspended between wakes. This happens on battery and also on AC power (first written as battery only; corrected after the run of 2026-11-13, checked on `pmset -g log`). Runs of 3-10 hours of wall clock against about 100-300 s of work ended with exit code 0 and complete data. Some runs also start at 04:00-04:11 instead of 02:00 (cause not checked). Decision (owner, 2026-11-11): no `caffeinate`; a slow night is accepted.
- **Network right after the wake:** Wi-Fi is often not up when the job starts; uv (PyPI), STAC and S3 then fail on "could not resolve host" (runs of 2026-11-18, 11-21, 11-22). Guards: `run-daily.sh` waits up to 10 minutes for the network first (`NETWORK_WAIT_S`); STAC search and granule reads retry 6 times with waits of 15-240 s (about 8 minutes) and a 60 s limit per STAC response; GDAL has HTTP time limits (60 s, connect 15 s). A day that still fails is picked up by the next run (3-day lookback). Not yet seen: a real wake where the 10-minute wait was needed.
- **Routine (owner, from 2026-11-11):** besides the 02:00 job, the owner asks for an update when wanted; then `scripts/run-daily.sh` is started by hand and, after `source-coop login`, published. The upload runs over mobile Wi-Fi, so check the volume first with `aws s3 sync publish/ s3://smartmaps/foil4gr1/snow-hokkaido/ --profile source-coop --endpoint-url https://data.source.coop --dryrun` (after `just publish` has staged). Measured: about 3-5 MB per new day; 33 MB for 9 days, 23 MB for 4 days, 19 MB for 3 days. `series/*.json` (about 5 MB) and `derived` (about 2 MB) go up in full every time, and every `state-*` tile from the first changed day on is uploaded again.
- **Update frequency (measured 2026-11-12, 2024-08-01 to 2026-11-11):** 953 passes in 833 days; 812 days (97%) have a pass; mean gap between passes 21.0 h, median 23.5 h, max 72.2 h; acquisitions at 09:54-10:42 JST. Days with at least 20% of Hokkaido land seen clear (SCL, not cloud or shadow): 44%, with a mean gap of 2.4 days (median 2, p90 5, max 23). Earth Search item `created` is about 4.3 h after acquisition (12 items; the meaning of `created` is not checked); the 02:00 run therefore picks passes up about 16 h after acquisition. Summarized in README.md (更新の頻度).
- **Measured:** one run with one new pass took 80 s (lookback 1) and 290 s (lookback 3) in the 2026 season (state replay from 2026-08-01); the replay grows by about 6 s per calendar day until the next 1 August. The incremental state (resume from a snapshot) is therefore not needed yet.
- Not done: incremental state; `superseded_by`; alerting by other means than the macOS notification.
