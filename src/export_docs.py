"""Export light derived files for the docs/ site (Pages): series JSON (tabularmaps contract) and stage1.json (legend, as-of).

No municipality boundary geometry is exported (derived from MLIT N03; see README).

Series contract (tabularmaps/do): {label, unit, asOf, min, max, values: {<5-digit code>: number}, notes: {code: str}}.
Rates are computed here from event counts; counts are the stored fact.
"""
import argparse
import glob
import json
from pathlib import Path

import pandas as pd

# obs class -> RGBA (0 no data, 1 cloud, 2 shadow, 3 green, 4 snow)
# Alpha is 0 or 255 only: partial alpha / raster-opacity < 1 rendered black in the embedded browser.
PALETTE = {0: (0, 0, 0, 0), 1: (235, 235, 245, 255), 2: (70, 50, 110, 255),
           3: (110, 175, 110, 255), 4: (40, 150, 255, 255)}


def season_of(ev):
    d = ev["obs_start_utc"].iloc[0].tz_convert("Asia/Tokyo")
    return d.year if d.month >= 8 else d.year - 1


WARDS = [f"011{i:02d}" for i in range(1, 11)]  # N03 has the ten Sapporo wards; the tabular layout also uses 01100 for the city


def add_sapporo(df, count_cols, weight_col=None, mean_col=None):
    """Append a Sapporo city row (code 01100) that sums the ten wards, keeping the ward rows."""
    w = df[df.muni_code.isin(WARDS)]
    if w.empty or (df.muni_code == "01100").any():
        return df
    row = {c: w[c].sum() for c in count_cols}
    for c in df.columns:
        if c not in row:
            row[c] = w[c].iloc[0] if c in ("date", "obs_start_utc", "algo_version") else None
    row["muni_code"] = "01100"
    if mean_col is not None:  # weighted mean of a per-ward statistic (age_median is only approximate for the city)
        wt = w[weight_col]
        row[mean_col] = float((w[mean_col] * wt).sum() / wt.sum()) if wt.sum() else None
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)


TS_COUNTS = ["n_land", "n_scanned", "n_cloud", "n_shadow", "n_clear", "n_clear_canopy", "n_clear_valid", "n_snow", "n_marginal", "n_nosnow"]
TS_METRICS = {  # key -> (label, numerator column, denominator column); same definitions as the single-date series
    "snow_rate": ("積雪率 (確認できたセル中)", "n_snow", "n_clear_valid"),
    "cloud_rate": ("雲の割合 (走査できたセル中)", "n_cloud", "n_scanned"),
    "visible_rate": ("見えた割合 (陸セル全体中)", "n_clear_valid", "n_land"),
    "scan_rate": ("走査できた割合 (陸セル全体中)", "n_scanned", "n_land"),
}


def build_ts(day_df, key):
    """Time series of one metric from the daily counts: {dates, values: {code: [value or None per date]}}.

    A municipality with no scanned cell on a date has no row, so its value is None (null in JSON).
    Sapporo's ten wards are also summed into the city code 01100 for every date.
    """
    label, num, den = TS_METRICS[key]
    parts = [add_sapporo(g.reset_index(drop=True), TS_COUNTS) for _, g in day_df.groupby("date")]
    full = pd.concat(parts, ignore_index=True)
    dates = sorted(full["date"].unique())
    values = {}
    for code, g in full.groupby("muni_code"):
        by_date = {r.date: pct(getattr(r, num), getattr(r, den)) for r in g.itertuples()}
        values[code] = [by_date.get(d) for d in dates]
    return {"label": label, "unit": "%", "min": 0, "max": 100, "dates": dates, "values": values}


STATE_TS = {  # last-known measures per calendar day, from derived/state: key -> (label, numerator column)
    "snow_rate_last": ("積雪率・最終既知 (見えたことのあるセル中)", "n_snow"),
    "freshness": ("鮮度 (最終既知のうち7日以内に見えたセル)", "n_fresh"),
}


def build_state_ts(state_df, key):
    """Per calendar day series of a last-known measure: numerator / (n_green + n_snow); None when no cell was ever seen."""
    label, num = STATE_TS[key]
    df = state_df.copy()
    df["n_known"] = df.n_green + df.n_snow
    cols = ["n_green", "n_snow", "n_unknown", "n_invalid", "n_fresh", "n_known"]
    parts = [add_sapporo(g.reset_index(drop=True), cols) for _, g in df.groupby("date")]
    full = pd.concat(parts, ignore_index=True)
    dates = sorted(full["date"].unique())
    values = {}
    for code, g in full.groupby("muni_code"):
        by_date = {r.date: pct(getattr(r, num), r.n_known) for r in g.itertuples()}
        values[code] = [by_date.get(d) for d in dates]
    return {"label": label, "unit": "%", "min": 0, "max": 100, "dates": dates, "values": values}


def pct(num, den):
    return None if den == 0 else round(100 * num / den, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default="ledger")
    ap.add_argument("--out", default="docs/data")
    a = ap.parse_args()
    out = Path(a.out)
    (out / "series").mkdir(parents=True, exist_ok=True)

    ev_path = sorted(glob.glob(f"{a.ledger}/events/season=*/part-*.parquet"))[-1]
    ev = pd.read_parquet(ev_path)
    ev = add_sapporo(ev, ["n_land", "n_scanned", "n_cloud", "n_shadow", "n_clear", "n_clear_canopy", "n_clear_valid", "n_snow", "n_marginal", "n_nosnow"])
    as_of_utc = ev["obs_start_utc"].iloc[0]
    as_of = as_of_utc.tz_convert("Asia/Tokyo").strftime("%Y-%m-%d %H:%M JST")
    n_gran = len(ev["sources"].iloc[0])
    scene = f"{n_gran} granules"  # keep asOf short; the full ids are in events.sources

    series = {
        "snow_rate": ("積雪率 (確認できたセル中)", "n_snow / n_clear_valid"),
        "cloud_rate": ("雲の割合 (走査できたセル中)", "n_cloud / n_scanned"),
        "visible_rate": ("見えた割合 (陸セル全体中)", "n_clear_valid / n_land"),
        "scan_rate": ("走査できた割合 (陸セル全体中)", "n_scanned / n_land"),
    }
    for key, (label, formula) in series.items():
        values, notes = {}, {}
        for r in ev.itertuples():
            if key == "snow_rate":
                v = pct(r.n_snow, r.n_clear_valid)
                hi = pct(r.n_snow + r.n_marginal, r.n_clear_valid)
                note = f"{r.n_snow:,} / {r.n_clear_valid:,} セル (閾値付近を含めると {hi}%)"
            elif key == "cloud_rate":
                v = pct(r.n_cloud, r.n_scanned)
                note = f"{r.n_cloud:,} / {r.n_scanned:,} セル"
            elif key == "scan_rate":
                v = pct(r.n_scanned, r.n_land)
                note = f"{r.n_scanned:,} / {r.n_land:,} セル"
            else:
                v = pct(r.n_clear_valid, r.n_land)
                note = f"{r.n_clear_valid:,} / {r.n_land:,} セル"
            if v is not None:
                values[r.muni_code] = v
                notes[r.muni_code] = note
        doc = {"label": label, "unit": "%", "asOf": f"{as_of} ({scene})", "min": 0, "max": 100,
               "values": values, "notes": notes, "formula": formula}
        (out / "series" / f"{key}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1))

    # time series (one value per observed day) from derived/daily
    dp = f"{a.ledger}/derived/daily/season={season_of(ev)}.parquet"
    if Path(dp).exists():
        day_df = pd.read_parquet(dp)
        for key in TS_METRICS:
            doc = build_ts(day_df, key)
            (out / "series" / f"{key}_ts.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))

    sp0 = f"{a.ledger}/derived/state/season={season_of(ev)}.parquet"
    if Path(sp0).exists():
        state_df = pd.read_parquet(sp0)
        for key in STATE_TS:
            (out / "series" / f"{key}_ts.json").write_text(
                json.dumps(build_state_ts(state_df, key), ensure_ascii=False, separators=(",", ":")))

    # last-known series from derived/state (latest date): snow rate among cells seen clear, and freshness
    sp = f"{a.ledger}/derived/state/season={season_of(ev)}.parquet"
    if Path(sp).exists():
        st = pd.read_parquet(sp)
        st = st[st.date == st.date.max()].copy()
        st["n_known"] = st.n_green + st.n_snow
        st = add_sapporo(st, ["n_green", "n_snow", "n_unknown", "n_invalid", "n_fresh", "n_known"], weight_col="n_known", mean_col="age_median")
        known = st.n_green + st.n_snow
        for key, label, num, den_note in (
            ("snow_rate_last", "積雪率・最終既知 (見えたことのあるセル中)", st.n_snow, "n_snow / (n_green + n_snow)"),
            ("freshness", "鮮度 (最終既知のうち7日以内に見えたセル)", st.n_fresh, "n_fresh / (n_green + n_snow)"),
        ):
            values, notes = {}, {}
            for r, kn in zip(st.itertuples(), known):
                if kn == 0:
                    continue
                n = r.n_snow if key == "snow_rate_last" else r.n_fresh
                values[r.muni_code] = round(100 * n / kn, 1)
                notes[r.muni_code] = f"{n:,} / {kn:,} セル、古さの中央値 {r.age_median:.0f} 日、一度も見えていない {r.n_unknown:,} セル"
            doc = {"label": label, "unit": "%", "asOf": st.date.iloc[0], "min": 0, "max": 100, "values": values, "notes": notes, "formula": den_note}
            (out / "series" / f"{key}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1))

    meta = {"asOf": as_of, "scene": scene,
            "classes": {"0": "走査外", "1": "雲", "2": "影", "3": "緑 (雪なし)", "4": "雪"},
            "colors": {k: "#%02x%02x%02x" % v[:3] for k, v in PALETTE.items() if k},
            "algo_version": ev["algo_version"].iloc[0]}
    (out / "stage1.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print("exported", sorted(p.name for p in out.rglob("*") if p.is_file()))


if __name__ == "__main__":
    main()
