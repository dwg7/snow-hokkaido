"""Build events/season=YYYY/part-*.parquet: one row per municipality per obs file (obs x cellmap GROUP BY)."""
import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

NDSI_THRESHOLD = 0.42
MARGIN_DELTA = 0.05  # provisional: |NDSI - threshold| <= delta is "marginal"
STATIC_LAKE, STATIC_SEA, STATIC_CANOPY = 2, 4, 1  # static_flags bits
QC_REFLECTANCE = 1  # qc_flags bit0: B03 negative-reflectance share above the (provisional) threshold
NEG_B03_MAX = 0.25  # provisional; set after checking more scenes

COUNT_COLS = ["n_land", "n_scanned", "n_cloud", "n_shadow", "n_clear", "n_clear_canopy",
              "n_clear_valid", "n_snow", "n_marginal", "n_nosnow"]


def build_events(cls, ndsi_q, muni_index, flags, master, meta):
    """Aggregate per-cell obs arrays by municipality. All arrays are (n, n); returns a DataFrame."""
    land = (muni_index > 0) & ((flags & (STATIC_LAKE | STATIC_SEA)) == 0)
    canopy = (flags & STATIC_CANOPY) != 0
    ndsi = ndsi_q.astype("float64") / 100 - 1
    clear = land & np.isin(cls, (3, 4))
    valid = clear & ~canopy
    marginal = valid & (np.abs(ndsi - NDSI_THRESHOLD) <= MARGIN_DELTA)
    masks = {
        "n_land": land,
        "n_scanned": land & np.isin(cls, (1, 2, 3, 4)),
        "n_cloud": land & (cls == 1),
        "n_shadow": land & (cls == 2),
        "n_clear": clear,
        "n_clear_canopy": clear & canopy,
        "n_clear_valid": valid,
        "n_snow": valid & (cls == 4) & ~marginal,
        "n_marginal": marginal,
        "n_nosnow": valid & (cls == 3) & ~marginal,
    }
    rows = []
    for r in master.itertuples():
        m = muni_index == r.muni_index
        row = {"muni_code": r.muni_code}
        row.update({k: int((v & m).sum()) for k, v in masks.items()})
        v = ndsi[valid & m]
        for q in (10, 50, 90):
            row[f"ndsi_p{q}"] = float(np.percentile(v, q)) if v.size else np.nan
        if row["n_land"] == 0:
            continue
        rows.append(row)
    df = pd.DataFrame(rows)
    for k, val in meta.items():
        df[k] = [val] * len(df) if isinstance(val, list) else val
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--obs", required=True)
    ap.add_argument("--cellmap", default="ledger/grid/cellmap.tif")
    ap.add_argument("--master", default="ledger/muni/master.parquet")
    ap.add_argument("--out", default="ledger")
    a = ap.parse_args()

    with rasterio.open(a.obs) as d:
        cls, ndsi_q = d.read(1), d.read(2)
        tags = d.tags()
    with rasterio.open(a.cellmap) as d:
        muni_index, flags = d.read(1), d.read(2)
    master = pd.read_parquet(a.master)

    digest = hashlib.sha1(Path(a.obs).read_bytes()).hexdigest()[:12]
    meta = {
        "sensor": "s2",
        "obs_start_utc": pd.Timestamp(tags["obs_start_utc"]),
        "obs_end_utc": pd.Timestamp(tags["obs_end_utc"]),
        "sun_elev_deg": np.float32(tags["sun_elevation"]),
        "sources": [tags["scene"]],
        "cell_zoom": np.uint8(int(tags["zoom"])),
        "qc_flags": np.uint16(QC_REFLECTANCE if float(tags.get("qc_neg_b03_frac", 0)) > NEG_B03_MAX else 0),
        "algo_version": tags["algo_version"],
        "superseded_by": None,
        "processed_at": pd.Timestamp(datetime.now(timezone.utc)),
    }
    df = build_events(cls, ndsi_q, muni_index, flags, master, meta)
    df.insert(0, "event_id", df["muni_code"] + "-" + digest)
    df = df.sort_values(["muni_code", "obs_start_utc"]).reset_index(drop=True)
    for c in COUNT_COLS:
        df[c] = df[c].astype("uint32")

    season = Path(a.obs).parent.name
    out = Path(a.out) / "events" / season
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"part-{Path(a.obs).stem}.parquet"
    df.to_parquet(path, index=False)
    print(df[["muni_code"] + COUNT_COLS].to_string())
    print("wrote", path)


if __name__ == "__main__":
    main()
