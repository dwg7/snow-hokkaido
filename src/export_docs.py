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
from PIL import Image
from pyproj import Transformer
from shapely.geometry import box, mapping
from shapely.ops import unary_union

# obs class -> RGBA (0 no data, 1 cloud, 2 shadow, 3 green, 4 snow)
# Alpha is 0 or 255 only: partial alpha / raster-opacity < 1 rendered black in the embedded browser.
PALETTE = {0: (0, 0, 0, 0), 1: (235, 235, 245, 255), 2: (70, 50, 110, 255),
           3: (110, 175, 110, 255), 4: (40, 150, 255, 255)}


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
    scene = ev["sources"].iloc[0][0]

    series = {
        "snow_rate": ("積雪率 (確認できたセル中)", "n_snow / n_clear_valid"),
        "cloud_rate": ("雲の割合 (走査できたセル中)", "n_cloud / n_scanned"),
        "visible_rate": ("見えた割合 (陸セル中)", "n_clear_valid / n_land"),
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
            else:
                v = pct(r.n_clear_valid, r.n_land)
                note = f"{r.n_clear_valid:,} / {r.n_land:,} セル"
            if v is not None:
                values[r.muni_code] = v
                notes[r.muni_code] = note
        doc = {"label": label, "unit": "%", "asOf": f"{as_of} ({scene})", "min": 0, "max": 100,
               "values": values, "notes": notes, "formula": formula}
        (out / "series" / f"{key}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1))

    # class raster -> RGBA PNG, with geographic corners
    obs_path = sorted(glob.glob(f"{a.ledger}/obs/season=*/*_s2.tif"))[-1]
    with rasterio.open(obs_path) as d:
        cls = d.read(1)
        l, b, r_, t = d.bounds
    lut = np.array([PALETTE[i] for i in range(5)], dtype=np.uint8)
    Image.fromarray(lut[np.clip(cls, 0, 4)], "RGBA").save(out / "obs-class.png", optimize=True)
    to_ll = Transformer.from_crs(3857, 4326, always_xy=True)
    (w, n), (e, s) = to_ll.transform(l, t), to_ll.transform(r_, b)

    # municipality outlines clipped to the tile, lightly simplified
    gdf = gpd.read_file(a.n03)
    ext = box(w, s, e, n)
    gdf = gdf[gdf.intersects(ext)]
    master = pd.read_parquet(f"{a.ledger}/muni/master.parquet").set_index("muni_code")
    feats = []
    for code, g in gdf.groupby("N03_007"):
        if code not in master.index:
            continue
        geom = unary_union(list(g.geometry)).intersection(ext).simplify(0.0002)
        feats.append({"type": "Feature", "geometry": mapping(geom),
                      "properties": {"code": code, "name": master.loc[code, "name"]}})
    (out / "muni-stage1.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                                                       ensure_ascii=False, separators=(",", ":")))

    meta = {"tile": "9/459/186", "asOf": as_of, "scene": scene, "bbox": [w, s, e, n],
            "coordinates": [[w, n], [e, n], [e, s], [w, s]],
            "classes": {"0": "走査外", "1": "雲", "2": "影", "3": "緑 (雪なし)", "4": "雪"},
            "colors": {k: "#%02x%02x%02x" % v[:3] for k, v in PALETTE.items() if k},
            "algo_version": ev["algo_version"].iloc[0]}
    (out / "stage1.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print("exported", sorted(p.name for p in out.rglob("*") if p.is_file()))


if __name__ == "__main__":
    main()
