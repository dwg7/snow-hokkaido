"""Replay the obs log into the cell ledger and write the "last known" products.

Sweeps the calendar days from the first day with obs of the season up to --upto, feeding pixel.Folder one day at
a time (a pure replay of the append-only obs log; nothing depends on an earlier snapshot). For every day it writes
- derived/state rows (municipality x date; HANDOFF appendix A) into ledger/derived/state/season=YYYY.parquet,
- unless --no-tiles, a raster PMTiles docs/data/view/state-<date>.pmtiles (state x age bucket),
and for the last day the cell ledger itself as ledger/pixel/season=YYYY/<date>.tif (a cache, git-ignored).
"""
import argparse
import glob
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

from make_view_tiles import STATE_PALETTE, STATE_RANK, load_day, update_dates_json, write_pmtiles
from make_events import COUNT_COLS, build_events
from pixel import STATE_GREEN, STATE_SNOW, STATE_UNKNOWN, Folder, age_days, season_start, state, state_index

STATIC_LAKE, STATIC_SEA, STATIC_CANOPY = 2, 4, 1
FRESH_DAYS = 7  # n_fresh counts cells last seen clear within this many days (provisional; D7)


def muni_rows(day_date, today_day, ledger, muni_index, land, valid, master, k):
    st = state(ledger, valid)
    age = age_days(ledger, today_day)
    flat = muni_index.ravel()

    def count(mask):
        return np.bincount(flat[mask.ravel()], minlength=k)[1:k]

    seen = land & ((st == STATE_GREEN) | (st == STATE_SNOW))
    df = pd.DataFrame({
        "muni_code": master.sort_values("muni_index").muni_code.to_numpy(),
        "date": day_date.isoformat(),
        "n_green": count(land & (st == STATE_GREEN)),
        "n_snow": count(land & (st == STATE_SNOW)),
        "n_unknown": count(land & valid & (st == STATE_UNKNOWN)),
        "n_invalid": count(land & ~valid),
        "n_fresh": count(seen & (age <= FRESH_DAYS)),
    })
    ages = pd.DataFrame({"m": flat[seen.ravel()], "a": age.ravel()[seen.ravel()]}).groupby("m")["a"].median()
    df["age_median"] = ages.reindex(range(1, k)).to_numpy()
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upto", required=True, help="last JST date YYYY-MM-DD")
    ap.add_argument("--ledger", default="ledger")
    ap.add_argument("--out", default="docs/data/view")
    ap.add_argument("--no-tiles", action="store_true")
    ap.add_argument("--tiles-from", help="only write the per-day PMTiles for dates on or after this JST date (the state is still replayed from the start)")
    a = ap.parse_args()

    upto = date.fromisoformat(a.upto)
    start = season_start(upto)
    obs_days = sorted(Path(p).name for p in glob.glob(f"{a.ledger}/obs/season={start.year}/*") if Path(p).name <= a.upto)
    if not obs_days:
        raise SystemExit("no obs up to that date")
    first = date.fromisoformat(obs_days[0])

    with rasterio.open(f"{a.ledger}/grid/cellmap.tif") as cm:
        muni_index, flags = cm.read(1), cm.read(2)
        z9 = tuple(map(int, cm.tags()["z9_tiles"].split("/")))
        profile, bounds, tf = cm.profile, cm.bounds, cm.transform
    master = pd.read_parquet(f"{a.ledger}/muni/master.parquet")
    k = int(master.muni_index.max()) + 1
    land = (muni_index > 0) & ((flags & (STATIC_LAKE | STATIC_SEA)) == 0)
    valid = land & ((flags & STATIC_CANOPY) == 0)

    folder = Folder(muni_index.shape, valid)
    rows, daily, d, t0 = [], [], first, time.time()
    while d <= upto:
        di = (d - start).days + 1
        if d.isoformat() in obs_days:
            with rasterio.open(f"{a.ledger}/grid/cellmap.tif") as cm:
                cls, ndsi_q, _ = load_day(a.ledger, d.isoformat(), cm)
            folder.update(di, cls)
            # the day's own counts (one observation per cell per day), same definitions as events
            day = build_events(cls, ndsi_q, muni_index, flags, master, {})
            day.insert(1, "date", d.isoformat())
            daily.append(day)
        led = folder.ledger()
        rows.append(muni_rows(d, di, led, muni_index, land, valid, master, k))
        if not a.no_tiles and (not a.tiles_from or d.isoformat() >= a.tiles_from):
            idx = state_index(led, di, valid)
            n, bbox = write_pmtiles(Path(a.out) / f"state-{d.isoformat()}.pmtiles", idx, bounds, z9, STATE_PALETTE, STATE_RANK,
                                    f"snow-hokkaido last known state {d.isoformat()} (JST)",
                                    "1-5 green (fresh to old), 6-10 snow (fresh to old); age buckets <=1, <=3, <=7, <=14, older days",
                                    {"fresh_days": FRESH_DAYS})
            update_dates_json(Path(a.out), bbox)
        print(f"{d}: day {di}, {'obs' if d.isoformat() in obs_days else 'no obs'}, {time.time() - t0:.0f}s", flush=True)
        d += timedelta(days=1)

    out = Path(a.ledger) / "derived" / "state"
    out.mkdir(parents=True, exist_ok=True)
    df = pd.concat(rows, ignore_index=True)
    for c in ("n_green", "n_snow", "n_unknown", "n_invalid", "n_fresh"):
        df[c] = df[c].astype("uint32")
    df.sort_values(["muni_code", "date"]).to_parquet(out / f"season={start.year}.parquet", index=False)

    dd = Path(a.ledger) / "derived" / "daily"
    dd.mkdir(parents=True, exist_ok=True)
    day_df = pd.concat(daily, ignore_index=True)
    for c in COUNT_COLS:
        day_df[c] = day_df[c].astype("uint32")
    day_df.sort_values(["muni_code", "date"]).to_parquet(dd / f"season={start.year}.parquet", index=False)

    led = folder.ledger()
    pix = Path(a.ledger) / "pixel" / f"season={start.year}"
    pix.mkdir(parents=True, exist_ok=True)
    prof = dict(driver="COG", width=muni_index.shape[1], height=muni_index.shape[0], count=6, dtype="uint16",
                crs=profile["crs"], transform=tf, compress="deflate", blocksize=512)
    with rasterio.open(pix / f"{upto.isoformat()}.tif", "w", **prof) as dst:
        for i, (name, arr) in enumerate(led.items(), 1):
            dst.write(arr.astype("uint16"), i)
            dst.set_band_description(i, name)
        dst.update_tags(season_start=start.isoformat(), day=str((upto - start).days + 1), first_obs_day=first.isoformat(),
                        note="cache: replay of the obs log (src/pixel.py Folder); day numbers are 1-based from season_start (JST)")
    print(f"wrote {out / f'season={start.year}.parquet'} ({len(df)} rows) and {pix / f'{upto.isoformat()}.tif'}")


if __name__ == "__main__":
    main()
