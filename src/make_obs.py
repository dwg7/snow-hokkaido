"""Build obs/season=YYYY/<date>_s2.tif (class, ndsi_q, clear_pct) for one z9 tile from one Sentinel-2 L2A scene.

10 m pixels (B03, B11 resampled to 10 m, SCL) are aggregated into z18 cells.
class: 0 no data, 1 cloud, 2 shadow, 3 green (clear, no snow), 4 snow.
"""
import argparse
import json
import math
import urllib.request
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.windows import Window, from_bounds
from pyproj import Transformer

Z = 18
R = 6378137.0
ORIGIN = math.pi * R
CELL_M = 2 * ORIGIN / 2**Z
STAC = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-c1-l2a"  # canonical (docs/timeseries-spec.md): COG metadata carries scale/offset
ALGO_VERSION = "algo-v1-dev"
NDSI_THRESHOLD = 0.42  # Sen2Cor value; no extra reflectance condition yet

# SCL classes -> pixel class
SCL_CLOUD = (8, 9, 10)  # cloud medium/high probability, thin cirrus
SCL_SHADOW = (3,)
SCL_NODATA = (0, 1)  # no data, saturated/defective (unusable)
# everything else (2 dark, 4, 5, 6 water, 7 unclassified, 11 snow/ice) counts as clear


def stac_get(path):
    with urllib.request.urlopen(f"{STAC}{path}", timeout=60) as r:
        return json.load(r)


def find_item(date, collection):
    body = json.dumps({
        "collections": [collection], "bbox": [142.73, 43.58, 143.44, 44.09],
        "datetime": f"{date}T00:00:00Z/{date}T23:59:59Z", "limit": 20,
    }).encode()
    req = urllib.request.Request(f"{STAC}/search", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        feats = json.load(r)["features"]
    if not feats:
        raise SystemExit(f"no {collection} scene on {date}")
    return min(feats, key=lambda f: f["properties"].get("eo:cloud_cover", 100))


def tile_bounds_3857(tx, ty):
    n = 2 ** (Z - 9)
    x0, y0 = tx * n, ty * n
    west = -ORIGIN + x0 * CELL_M
    north = ORIGIN - y0 * CELL_M
    return x0, y0, n, west, north - n * CELL_M, west + n * CELL_M, north


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="UTC date YYYY-MM-DD")
    ap.add_argument("--item", help="STAC item id (default: lowest-cloud scene on the date)")
    ap.add_argument("--tile", default="9/459/186")
    ap.add_argument("--out", default="ledger")
    ap.add_argument("--collection", default=COLLECTION, choices=["sentinel-2-l2a", "sentinel-2-c1-l2a"])
    a = ap.parse_args()

    item = stac_get(f"/collections/{a.collection}/items/{a.item}") if a.item else find_item(a.date, a.collection)
    props = item["properties"]
    hrefs = {k: item["assets"][k]["href"] for k in ("green", "swir16", "scl")}
    _, tx, ty = map(int, a.tile.split("/"))
    x0, y0, n, west, south, east, north = tile_bounds_3857(tx, ty)

    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="3"):
        with rasterio.open(hrefs["green"]) as g:
            utm = g.crs
            to_utm = Transformer.from_crs(3857, utm, always_xy=True)
            to_3857 = Transformer.from_crs(utm, 3857, always_xy=True)
            # bounding box of the tile edges in the scene CRS
            t = np.linspace(0, 1, 41)
            ex = np.concatenate([west + t * (east - west), west + t * (east - west),
                                 np.full(41, west), np.full(41, east)])
            ey = np.concatenate([np.full(41, south), np.full(41, north),
                                 south + t * (north - south), south + t * (north - south)])
            ux, uy = to_utm.transform(ex, ey)
            win = from_bounds(ux.min(), uy.min(), ux.max(), uy.max(), g.transform)
            win = Window(math.floor(win.col_off), math.floor(win.row_off),
                         math.ceil(win.width) + 1, math.ceil(win.height) + 1)
            wt = g.window_transform(win)
            b = rasterio.windows.bounds(win, g.transform)
            shape = (int(win.height), int(win.width))
            # Scale/offset come from each file, not from STAC: the legacy l2a COGs carry none (DN = reflectance*10000
            # with the baseline offset already removed) while c1 COGs carry offset -0.1; STAC claims -0.1 for both.
            g_scale, g_off = g.scales[0], g.offsets[0]
            green = g.read(1, window=win).astype("float32")
            green_nodata = g.read(1, window=win) == (g.nodata if g.nodata is not None else 0)
        with rasterio.open(hrefs["swir16"]) as s:
            w = from_bounds(*b, s.transform)
            swir_raw = s.read(1, window=w, out_shape=shape, resampling=Resampling.bilinear,
                              boundless=True, fill_value=0)
            s_scale, s_off = s.scales[0], s.offsets[0]
            swir = swir_raw.astype("float32")
        with rasterio.open(hrefs["scl"]) as c:
            w = from_bounds(*b, c.transform)
            scl = c.read(1, window=w, out_shape=shape, resampling=Resampling.nearest,
                         boundless=True, fill_value=0)

    green = green * g_scale + g_off
    swir = swir * s_scale + s_off
    with np.errstate(divide="ignore", invalid="ignore"):
        ndsi = (green - swir) / (green + swir)
    nodata = green_nodata | (swir_raw == 0) | np.isin(scl, SCL_NODATA) | ~np.isfinite(ndsi)
    cloud = np.isin(scl, SCL_CLOUD) & ~nodata
    shadow = np.isin(scl, SCL_SHADOW) & ~nodata
    clear = ~(nodata | cloud | shadow)
    snow = clear & (ndsi >= NDSI_THRESHOLD)
    scl_snow = scl == 11
    print("pixel check: NDSI snow", int(snow.sum()), "SCL=11", int(scl_snow.sum()), "both", int((snow & scl_snow).sum()))
    green_c = clear & ~snow

    # QC recorded in the obs tags (docs/timeseries-spec.md, section 6): a wrong offset shows up as many
    # negative B03 reflectances; where snow exists, NDSI snow should mostly agree with SCL=11.
    valid_g = ~green_nodata
    qc_neg_b03 = float(((green < 0) & valid_g).sum() / max(int(valid_g.sum()), 1))
    qc_snow_in_scl = float((snow & scl_snow).sum() / snow.sum()) if snow.sum() >= 1000 else None

    # pixel centers -> cell index
    rows, cols = np.indices(shape)
    px = wt.c + (cols + 0.5) * wt.a
    py = wt.f + (rows + 0.5) * wt.e
    mx, my = to_3857.transform(px, py)
    ix = np.floor((mx + ORIGIN) / CELL_M).astype(int) - x0
    iy = np.floor((ORIGIN - my) / CELL_M).astype(int) - y0
    inside = (ix >= 0) & (ix < n) & (iy >= 0) & (iy < n)
    flat = (iy * n + ix)[inside]

    def count(mask):
        return np.bincount(flat, weights=mask[inside].astype("float64"), minlength=n * n).reshape(n, n)

    total = count(np.ones(shape, bool))
    n_cloud, n_shadow, n_nodata = count(cloud), count(shadow), count(nodata)
    n_snow, n_green = count(snow), count(green_c)
    n_clear = n_snow + n_green
    ndsi_sum = np.bincount(flat, weights=np.where(clear, ndsi, 0)[inside], minlength=n * n).reshape(n, n)

    cls = np.zeros((n, n), np.uint8)
    seen = total > 0
    is_clear = seen & (n_clear * 2 > total)
    cls[is_clear & (n_snow > n_green)] = 4
    cls[is_clear & (n_snow <= n_green)] = 3
    other = seen & ~is_clear
    stack = np.stack([n_nodata, n_cloud, n_shadow])  # class 0, 1, 2
    cls[other] = np.argmax(stack, axis=0)[other].astype(np.uint8)

    with np.errstate(divide="ignore", invalid="ignore"):
        mean_ndsi = ndsi_sum / n_clear
        clear_pct = np.where(seen, np.rint(100 * n_clear / total), 0).astype(np.uint8)
    ndsi_q = np.where(n_clear > 0, np.rint((np.nan_to_num(mean_ndsi) + 1) * 100), 255).clip(0, 255).astype(np.uint8)

    season = int(a.date[:4]) if int(a.date[5:7]) >= 8 else int(a.date[:4]) - 1
    out = Path(a.out) / "obs" / f"season={season}" / f"{a.date}_s2.tif"
    out.parent.mkdir(parents=True, exist_ok=True)
    prof = dict(driver="COG", width=n, height=n, count=3, dtype="uint8", crs="EPSG:3857",
                transform=from_origin(west, north, CELL_M, CELL_M), compress="deflate")
    with rasterio.open(out, "w", **prof) as dst:
        for i, (arr, name) in enumerate([(cls, "class"), (ndsi_q, "ndsi_q"), (clear_pct, "clear_pct")], 1):
            dst.write(arr, i)
            dst.set_band_description(i, name)
        dst.update_tags(
            tile=a.tile, zoom=str(Z), sensor="s2", scene=item["id"], stac_collection=a.collection,
            obs_start_utc=props["datetime"], obs_end_utc=props["datetime"],
            sun_elevation=str(props.get("view:sun_elevation")), algo_version=ALGO_VERSION,
            ndsi_threshold=str(NDSI_THRESHOLD), processing_baseline=str(props.get("s2:processing_baseline")),
            band_offsets=f"green={g_off},swir16={s_off}",
            note="scale/offset read from the COG files",
            datatake_id=str(props.get("s2:datatake_id")), product_uri=str(props.get("s2:product_uri")),
            qc_neg_b03_frac=f"{qc_neg_b03:.4f}",
            qc_ndsi_snow_in_scl_frac="na" if qc_snow_in_scl is None else f"{qc_snow_in_scl:.4f}",
        )

    vals, cnt = np.unique(cls, return_counts=True)
    print(item["id"], props["datetime"], "scene cloud", props.get("eo:cloud_cover"))
    print("offsets", g_off, s_off, "scales", g_scale, s_scale)
    print("class counts", dict(zip(vals.tolist(), cnt.tolist())))
    print("pixels per cell min/median/max", total[seen].min(), np.median(total[seen]), total[seen].max(), "empty cells", int((~seen).sum()))
    print("wrote", out)


if __name__ == "__main__":
    main()
