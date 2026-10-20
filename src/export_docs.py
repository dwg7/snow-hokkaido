"""Export light derived files for the docs/ site (Pages): series JSON (tabularmaps contract), class PNG, municipality GeoJSON.

Series contract (tabularmaps/do): {label, unit, asOf, min, max, values: {<5-digit code>: number}, notes: {code: str}}.
Rates are computed here from event counts; counts are the stored fact.
"""
import argparse
import glob
import json
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import shapely
from PIL import Image
from pyproj import Transformer
from shapely.geometry import mapping
from shapely.ops import unary_union

# obs class -> RGBA (0 no data, 1 cloud, 2 shadow, 3 green, 4 snow)
# Alpha is 0 or 255 only: partial alpha / raster-opacity < 1 rendered black in the embedded browser.
PALETTE = {0: (0, 0, 0, 0), 1: (235, 235, 245, 255), 2: (70, 50, 110, 255),
           3: (110, 175, 110, 255), 4: (40, 150, 255, 255)}


def season_of(ev):
    d = ev["obs_start_utc"].iloc[0].tz_convert("Asia/Tokyo")
    return d.year if d.month >= 8 else d.year - 1


def pct(num, den):
    return None if den == 0 else round(100 * num / den, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default="ledger")
    ap.add_argument("--n03", default="data/raw/n03-20260101/N03-20260101_01.shp")
    ap.add_argument("--out", default="docs/data")
    a = ap.parse_args()
    out = Path(a.out)
    (out / "series").mkdir(parents=True, exist_ok=True)

    ev_path = sorted(glob.glob(f"{a.ledger}/events/season=*/part-*.parquet"))[-1]
    ev = pd.read_parquet(ev_path)
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

    # last-known series from derived/state (latest date): snow rate among cells seen clear, and freshness
    sp = f"{a.ledger}/derived/state/season={season_of(ev)}.parquet"
    if Path(sp).exists():
        st = pd.read_parquet(sp)
        st = st[st.date == st.date.max()]
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

    # class raster -> RGBA PNG, with geographic corners
    obs_path = sorted(glob.glob(f"{a.ledger}/obs/season=*/*/*/459-186.tif"))[-1]  # stage-1 tile, latest pass
    with rasterio.open(obs_path) as d:
        cls = d.read(1)
        l, b, r_, t = d.bounds
    lut = np.array([PALETTE[i] for i in range(5)], dtype=np.uint8)
    Image.fromarray(lut[np.clip(cls, 0, 4)], "RGBA").save(out / "obs-class.png", optimize=True)
    to_ll = Transformer.from_crs(3857, 4326, always_xy=True)
    (w, n), (e, s) = to_ll.transform(l, t), to_ll.transform(r_, b)

    # municipality polygons for all of Hokkaido (hit-testing and popups), simplified to about 100 m
    gdf = gpd.read_file(a.n03)
    gdf = gdf[gdf["N03_007"].notna()]
    master = pd.read_parquet(f"{a.ledger}/muni/master.parquet").set_index("muni_code")
    feats = []
    for code, g in gdf.groupby("N03_007"):
        if code not in master.index:
            continue
        geom = shapely.set_precision(unary_union(list(g.geometry)).simplify(0.001, preserve_topology=True), 1e-4)
        feats.append({"type": "Feature", "geometry": mapping(geom),
                      "properties": {"code": code, "name": master.loc[code, "name"]}})
    (out / "muni.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                                                 ensure_ascii=False, separators=(",", ":")))
    (out / "muni-stage1.geojson").unlink(missing_ok=True)

    meta = {"tile": "9/459/186", "asOf": as_of, "scene": scene, "bbox": [w, s, e, n],
            "coordinates": [[w, n], [e, n], [e, s], [w, s]],
            "classes": {"0": "走査外", "1": "雲", "2": "影", "3": "緑 (雪なし)", "4": "雪"},
            "colors": {k: "#%02x%02x%02x" % v[:3] for k, v in PALETTE.items() if k},
            "algo_version": ev["algo_version"].iloc[0]}
    (out / "stage1.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print("exported", sorted(p.name for p in out.rglob("*") if p.is_file()))


if __name__ == "__main__":
    main()
