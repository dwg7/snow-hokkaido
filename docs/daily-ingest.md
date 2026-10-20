# Daily ingest (design, not implemented)

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
