"""Build events/season=YYYY/part-*.parquet: one row per municipality per obs file (obs x cellmap GROUP BY)."""
import argparse
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.windows import from_bounds

STATIC_LAKE, STATIC_SEA, STATIC_CANOPY = 2, 4, 1  # static_flags bits

COUNT_COLS = ["n_land", "n_scanned", "n_cloud", "n_shadow", "n_clear", "n_clear_canopy",
              "n_clear_valid", "n_snow", "n_nosnow"]


def build_events(cls, muni_index, flags, master, meta):
    """Aggregate per-cell obs arrays by municipality. All arrays share one shape; returns a DataFrame.

    Cells not covered by the pass must be class 0 (not scanned); n_land counts every land cell of the
    municipality, so it equals master.n_land_cells and scan_rate = n_scanned / n_land shows coverage.
    Municipalities with no scanned cell are skipped (the pass did not touch them).
    """
    k = int(master.muni_index.max()) + 1
    land = (muni_index > 0) & ((flags & (STATIC_LAKE | STATIC_SEA)) == 0)
    canopy = (flags & STATIC_CANOPY) != 0
    clear = land & np.isin(cls, (3, 4))
    valid = clear & ~canopy
    masks = {
        "n_land": land,
        "n_scanned": land & np.isin(cls, (1, 2, 3, 4)),
        "n_cloud": land & (cls == 1),
        "n_shadow": land & (cls == 2),
        "n_clear": clear,
        "n_clear_canopy": clear & canopy,
        "n_clear_valid": valid,
        "n_snow": valid & (cls == 4),
        "n_nosnow": valid & (cls == 3),
    }
    flat = muni_index.ravel()
    counts = {name: np.bincount(flat[m.ravel()], minlength=k)[1:k] for name, m in masks.items()}
    df = pd.DataFrame(counts)
    df.insert(0, "muni_code", master.sort_values("muni_index").muni_code.to_numpy())
    df = df[df.n_scanned > 0].reset_index(drop=True)
    for key, val in meta.items():
        df[key] = [val] * len(df) if isinstance(val, list) else val
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--obs", required=True, nargs="+", help="obs files of one pass, or the pass directory")
    ap.add_argument("--cellmap", default="ledger/grid/cellmap.tif")
    ap.add_argument("--master", default="ledger/muni/master.parquet")
    ap.add_argument("--out", default="ledger")
    a = ap.parse_args()

    with rasterio.open(a.cellmap) as d:
        muni_index, flags = d.read(1), d.read(2)
        cm_tf, cm_shape = d.transform, d.shape
    master = pd.read_parquet(a.master)
    paths = []
    for p in a.obs:
        paths += sorted(Path(p).rglob("*.tif")) if Path(p).is_dir() else [Path(p)]
    cls = np.zeros(cm_shape, np.uint8)
    tags, scenes, starts, ends = None, [], [], []
    for path in paths:  # obs files of one pass (one per z9 tile); everything else stays class 0
        with rasterio.open(path) as d:
            t = d.tags()
            scenes.extend(t["scene"].split(",")); starts.append(t["obs_start_utc"]); ends.append(t["obs_end_utc"])
            w = from_bounds(*d.bounds, cm_tf)
            r0, c0 = round(w.row_off), round(w.col_off)
            cls[r0:r0 + d.height, c0:c0 + d.width] = d.read(1)
        if tags is None:
            tags = t
        elif t["datatake_id"] != tags["datatake_id"]:
            raise SystemExit(f"obs files are from different passes: {path}")

    digest = hashlib.sha1(tags["datatake_id"].encode()).hexdigest()[:12]  # event id keyed by pass
    meta = {
        "sensor": "s2",
        "obs_start_utc": min(pd.Timestamp(x) for x in starts),
        "obs_end_utc": max(pd.Timestamp(x) for x in ends),
        "sun_elev_deg": np.float32(tags["sun_elevation"]),
        "sources": sorted(set(scenes)),
        "cell_zoom": np.uint8(int(tags["zoom"])),
        "algo_version": tags["algo_version"],
        "superseded_by": None,
        "processed_at": pd.Timestamp(datetime.now(timezone.utc)),
    }
    df = build_events(cls, muni_index, flags, master, meta)
    df.insert(0, "event_id", df["muni_code"] + "-" + digest)
    df = df.sort_values(["muni_code", "obs_start_utc"]).reset_index(drop=True)
    for c in COUNT_COLS:
        df[c] = df[c].astype("uint32")

    season = next(part for part in paths[0].parts if part.startswith("season="))
    out = Path(a.out) / "events" / season
    out.mkdir(parents=True, exist_ok=True)
    day = meta["obs_start_utc"].astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    path = out / f"part-{day}_{tags['datatake_id']}.parquet"
    df.to_parquet(path, index=False)
    print(df[["muni_code"] + COUNT_COLS].to_string())
    print("wrote", path)


if __name__ == "__main__":
    main()
