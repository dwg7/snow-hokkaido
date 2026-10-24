"""Build obs files (class, clear_pct per z18 cell) for one JST day, cutting scenes into z9 tiles.

Layout: <out>/obs/season=YYYY/<JST date>/<datatake_id>/<x>-<y>.tif, one file per pass and z9 tile
(docs/timeseries-spec.md, section 2). Granules of one pass that cover a tile are merged: a cell takes the
first granule (sorted by s2:tile_id) that scanned it.

10 m pixels (B03, B11 resampled to 10 m, SCL) are aggregated into cells.
class: 0 no data / not scanned, 1 cloud, 2 shadow, 3 green (clear, no snow), 4 snow.
"""
import argparse
import json
import math
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.windows import Window, from_bounds
from shapely.geometry import box, shape

Z = 18
R = 6378137.0
ORIGIN = math.pi * R
CELL_M = 2 * ORIGIN / 2**Z
N9 = 2 ** (Z - 9)  # cells per z9 tile edge
STAC = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-c1-l2a"  # canonical (docs/timeseries-spec.md): COG metadata carries scale/offset
ALGO_VERSION = "algo-v1-dev4"
SCL_SNOW = 11  # snow / ice in the L2A scene classification
SNOW_MIN_CLEAR_PCT = 80  # a cell is snow only if at least this share of its pixels was clear: snow next to cloud is doubtful (docs/validation-pixel-rule.md)
JST = timezone(timedelta(hours=9))
STEP = 32  # pixels between nodes of the pixel -> cell coordinate interpolation grid

# SCL classes -> pixel class
SCL_CLOUD = (8, 9, 10)  # cloud medium/high probability, thin cirrus
SCL_SHADOW = (3,)
SCL_NODATA = (0, 1)  # no data, saturated/defective (unusable)
# everything else (2 dark, 4, 5, 6 water, 7 unclassified, 11 snow/ice) counts as clear


def stac_search(body):
    req = urllib.request.Request(f"{STAC}/search", json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)["features"]


def day_items(d, bbox):
    """All c1-l2a items acquired on JST date d over bbox, one per s2:product_uri."""
    start = datetime(d.year, d.month, d.day, tzinfo=JST).astimezone(timezone.utc)
    end = start + timedelta(days=1) - timedelta(seconds=1)
    feats = stac_search({
        "collections": [COLLECTION], "bbox": bbox, "limit": 500,
        "datetime": f"{start:%Y-%m-%dT%H:%M:%SZ}/{end:%Y-%m-%dT%H:%M:%SZ}",
    })
    seen, out = set(), []
    for f in sorted(feats, key=lambda f: f["id"]):
        uri = f["properties"]["s2:product_uri"]
        if uri not in seen:
            seen.add(uri)
            out.append(f)
    return out


def tile_geom(tx, ty):
    """z9 tile as (cell origin x0, y0, EPSG:3857 bounds west, south, east, north, lon/lat box)."""
    x0, y0 = tx * N9, ty * N9
    west = -ORIGIN + x0 * CELL_M
    north = ORIGIN - y0 * CELL_M
    east, south = west + N9 * CELL_M, north - N9 * CELL_M
    to_ll = Transformer.from_crs(3857, 4326, always_xy=True)
    (w, n), (e, s) = to_ll.transform(west, north), to_ll.transform(east, south)
    return x0, y0, (west, south, east, north), box(w, s, e, n)


def land_tiles(cellmap_path):
    """z9 tiles (x, y) of the cellmap mosaic that contain any land cell."""
    with rasterio.open(cellmap_path) as d:
        land = d.read(1) > 0
        tx0, ty0, _, _ = map(int, d.tags()["z9_tiles"].split("/"))
    h, w = land.shape
    blocks = land.reshape(h // N9, N9, w // N9, N9).any(axis=(1, 3))
    return [(int(tx0 + c), int(ty0 + r)) for r, c in zip(*np.nonzero(blocks))]


def read_window(ds, window, shape, resampling):
    """Read band 1 into `shape`; fill with 0 where the window leaves the dataset."""
    inside = (window.col_off >= 0 and window.row_off >= 0 and window.col_off + window.width <= ds.width
              and window.row_off + window.height <= ds.height)
    if inside:
        return ds.read(1, window=window, out_shape=shape, resampling=resampling)
    return ds.read(1, window=window, out_shape=shape, resampling=resampling, boundless=True, fill_value=0)


def cell_coords(wt, shape, to_3857, x0, y0):
    """Continuous cell coordinates (relative to the tile) of every pixel center, via a coarse node grid."""
    nr, nc = (shape[0] - 1) // STEP + 2, (shape[1] - 1) // STEP + 2
    rr, cc = np.arange(nr) * STEP, np.arange(nc) * STEP
    px = wt.c + (cc[None, :] + 0.5) * wt.a + (rr[:, None] + 0.5) * wt.b
    py = wt.f + (cc[None, :] + 0.5) * wt.d + (rr[:, None] + 0.5) * wt.e
    mx, my = to_3857.transform(px, py)
    gx = (mx + ORIGIN) / CELL_M - x0
    gy = (ORIGIN - my) / CELL_M - y0

    def up(nodes):  # separable linear interpolation of the node grid to every pixel
        r = np.arange(shape[0]) / STEP
        i = np.minimum(r.astype(int), nr - 2)
        f = (r - i)[:, None]
        tmp = nodes[i] * (1 - f) + nodes[i + 1] * f
        c = np.arange(shape[1]) / STEP
        j = np.minimum(c.astype(int), nc - 2)
        g = (c - j)[None, :]
        return (tmp[:, j] * (1 - g) + tmp[:, j + 1] * g).astype(np.float32)

    return up(gx), up(gy)


def process_granule(item, tx, ty):
    """Aggregate one granule into the z18 cells of z9 tile (tx, ty). Returns a dict or None if nothing scanned.

    Only SCL is read (algo-v1-dev4): snow is SCL class 11, as classified by the L2A processing. B03 and B11 are not
    read.
    """
    hrefs = {k: item["assets"][k]["href"] for k in ("green", "scl")}  # green: header only, for the 10 m window
    x0, y0, (west, south, east, north), _ = tile_geom(tx, ty)
    n = N9
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="3"):
        with rasterio.open(hrefs["green"]) as g:
            to_utm = Transformer.from_crs(3857, g.crs, always_xy=True)
            to_3857 = Transformer.from_crs(g.crs, 3857, always_xy=True)
            t = np.linspace(0, 1, 41)  # tile edges in the scene CRS -> pixel window
            ex = np.concatenate([west + t * (east - west), west + t * (east - west), np.full(41, west), np.full(41, east)])
            ey = np.concatenate([np.full(41, south), np.full(41, north), south + t * (north - south), south + t * (north - south)])
            ux, uy = to_utm.transform(ex, ey)
            win = from_bounds(ux.min(), uy.min(), ux.max(), uy.max(), g.transform)
            win = Window(math.floor(win.col_off), math.floor(win.row_off), math.ceil(win.width) + 1, math.ceil(win.height) + 1)
            if win.col_off + win.width <= 0 or win.row_off + win.height <= 0 or win.col_off >= g.width or win.row_off >= g.height:
                return None
            wt = g.window_transform(win)
            b = rasterio.windows.bounds(win, g.transform)
            shape = (int(win.height), int(win.width))
        with rasterio.open(hrefs["scl"]) as c:
            scl = read_window(c, from_bounds(*b, c.transform), shape, Resampling.nearest)

    nodata = np.isin(scl, SCL_NODATA)
    cloud = np.isin(scl, SCL_CLOUD)
    shadow = np.isin(scl, SCL_SHADOW)
    clear = ~(nodata | cloud | shadow)
    snow = clear & (scl == SCL_SNOW)
    green_c = clear & ~snow
    qc = {"snow": int(snow.sum()), "clear": int(clear.sum())}

    gx, gy = cell_coords(wt, shape, to_3857, x0, y0)
    ix, iy = np.floor(gx).astype(np.int32), np.floor(gy).astype(np.int32)
    inside = (ix >= 0) & (ix < n) & (iy >= 0) & (iy < n)
    flat = (iy * n + ix)[inside]

    def count(mask, weights=None):
        w = mask[inside].astype("float64") if weights is None else weights[inside]
        return np.bincount(flat, weights=w, minlength=n * n).reshape(n, n)

    total = count(np.ones(shape, bool))
    if total.sum() == 0:
        return None
    n_cloud, n_shadow, n_nodata = count(cloud), count(shadow), count(nodata)
    n_snow, n_green = count(snow), count(green_c)
    n_clear = n_snow + n_green

    cls = np.zeros((n, n), np.uint8)
    seen = total > 0
    is_clear = seen & (n_clear * 2 > total)
    snow_cell = is_clear & (n_snow > n_green) & (n_clear * 100 >= SNOW_MIN_CLEAR_PCT * total)
    is_clear &= ~((n_snow > n_green) & ~snow_cell)  # doubtful snow cells fall through to "not seen"
    cls[snow_cell] = 4
    cls[is_clear & (n_snow <= n_green)] = 3
    other = seen & ~is_clear
    cls[other] = np.argmax(np.stack([n_nodata, n_cloud, n_shadow]), axis=0)[other].astype(np.uint8)
    with np.errstate(divide="ignore", invalid="ignore"):
        clear_pct = np.where(seen, np.rint(100 * n_clear / total), 0).astype(np.uint8)
    return {"cls": cls, "clear_pct": clear_pct, "qc": qc,
            "pixels_per_cell": (int(total[seen].min()), float(np.median(total[seen])), int(total[seen].max()))}


def read_with_retry(item, tx, ty, attempts=4):
    """process_granule, retried: range reads from S3 sometimes come back short (CPLE_AppDefinedError / RasterioIOError)."""
    for k in range(attempts):
        try:
            return process_granule(item, tx, ty)
        except rasterio.errors.RasterioError:
            if k == attempts - 1:
                raise
            time.sleep(5 * 2 ** k)


def write_obs(path, tx, ty, parts, items, considered=None):
    """Write one pass x tile file from merged granule results."""
    cls, clear_pct = parts["cls"], parts["clear_pct"]
    x0, y0, (west, south, east, north), _ = tile_geom(tx, ty)
    qc = parts["qc"]
    p0 = items[0]["properties"]
    times = sorted(i["properties"]["datetime"] for i in items)
    path.parent.mkdir(parents=True, exist_ok=True)
    prof = dict(driver="COG", width=N9, height=N9, count=2, dtype="uint8", crs="EPSG:3857",
                transform=from_origin(west, north, CELL_M, CELL_M), compress="deflate")
    with rasterio.open(path, "w", **prof) as dst:
        for i, (arr, name) in enumerate([(cls, "class"), (clear_pct, "clear_pct")], 1):
            dst.write(arr, i)
            dst.set_band_description(i, name)
        dst.update_tags(
            tile=f"9/{tx}/{ty}", zoom=str(Z), sensor="s2", stac_collection=COLLECTION,
            granules_considered=",".join(sorted(c["properties"]["s2:product_uri"] for c in (considered or items))),
            scene=",".join(i["id"] for i in items), product_uri=",".join(i["properties"]["s2:product_uri"] for i in items),
            datatake_id=p0["s2:datatake_id"], obs_start_utc=times[0], obs_end_utc=times[-1],
            sun_elevation=str(np.mean([i["properties"].get("view:sun_elevation", np.nan) for i in items])),
            algo_version=ALGO_VERSION, snow_source="SCL class 11 (Sen2Cor scene classification)", snow_min_clear_pct=str(SNOW_MIN_CLEAR_PCT),
            processing_baseline=str(p0.get("s2:processing_baseline")),
            note="only SCL is read; overlapping granules: first by s2:tile_id wins",
            qc_clear_pixels=str(qc["clear"]), qc_snow_pixels=str(qc["snow"]),
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="JST date YYYY-MM-DD")
    ap.add_argument("--tiles", nargs="*", help="only these z9 tiles, as x/y (default: all land tiles the pass covers)")
    ap.add_argument("--cellmap", default="ledger/grid/cellmap.tif")
    ap.add_argument("--out", default="ledger")
    ap.add_argument("--workers", type=int, default=4, help="parallel pass x tile jobs (about 1.5 GB RAM each)")
    ap.add_argument("--touched", help="append the pass directory of every file written to this file")
    ap.add_argument("--force", action="store_true", help="rebuild files that already exist (default: skip complete ones)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and stop")
    a = ap.parse_args()

    d = date.fromisoformat(a.date)
    season = d.year if d.month >= 8 else d.year - 1
    tiles = land_tiles(a.cellmap)
    if a.tiles:
        want = {tuple(map(int, t.split("/"))) for t in a.tiles}
        tiles = [t for t in tiles if t in want]
    all_tiles_ll = [(t, tile_geom(*t)[3]) for t in tiles]
    bbox = [139.3, 41.3, 148.95, 45.6]
    items = day_items(d, bbox)
    passes = defaultdict(list)
    for it in items:
        passes[it["properties"]["s2:datatake_id"]].append(it)
    print(f"{a.date} JST: {len(items)} granules in {len(passes)} passes; {len(tiles)} land tiles")

    plan = []  # (datatake, tile, granules sorted by tile id)
    for dt, its in sorted(passes.items()):
        geoms = [(it, shape(it["geometry"])) for it in its]
        for t, tbox in all_tiles_ll:
            cover = sorted((it for it, g in geoms if g.intersects(tbox)), key=lambda i: i["properties"]["s2:tile_id"])
            if cover:
                plan.append((dt, t, cover))
    print(f"plan: {len(plan)} pass x tile files")
    if a.dry_run:
        for dt, t, cover in plan[:20]:
            print(" ", dt, t, [c["properties"]["grid:code"] for c in cover])
        return

    def done_already(out, cover):
        # A complete earlier result is reused (resume after an interruption). It is rebuilt when STAC now shows
        # granules for this pass and tile that the file did not consider (late arrivals), or when it is unreadable.
        if a.force or not out.exists():
            return False
        try:
            with rasterio.open(out) as d:
                tags = d.tags()
                if d.count != 2 or "obs_start_utc" not in tags:
                    return False
                seen = tags.get("granules_considered")  # files written before this tag existed count as complete
                return seen is None or set(seen.split(",")) == {c["properties"]["s2:product_uri"] for c in cover}
        except Exception:
            return False

    def run_one(job):
        dt, (tx, ty), cover = job
        t0 = time.time()
        out = Path(a.out) / "obs" / f"season={season}" / a.date / dt / f"{tx}-{ty}.tif"
        if done_already(out, cover):
            return f"  {dt} {tx}/{ty}: exists, skipped"
        merged, used = None, []
        for it in cover:
            r = read_with_retry(it, tx, ty)
            if r is None:
                continue
            used.append(it)
            if merged is None:
                merged = r
                continue
            fill = (merged["cls"] == 0) & (r["cls"] != 0)  # first scanned wins
            for k in ("cls", "clear_pct"):
                merged[k][fill] = r[k][fill]
            for k in merged["qc"]:
                merged["qc"][k] += r["qc"][k]
        if merged is None or not (merged["cls"] > 0).any():
            return f"  {dt} {tx}/{ty}: nothing scanned, skipped"
        write_obs(out, tx, ty, merged, used, cover)
        if a.touched:  # let a caller (daily.py) know which passes changed
            with open(a.touched, "a") as fh:
                fh.write(str(out.parent) + "\n")
        vals, cnt = np.unique(merged["cls"], return_counts=True)
        return f"  {dt} {tx}/{ty}: {len(used)} granule(s) {dict(zip(vals.tolist(), cnt.tolist()))} {time.time() - t0:.0f}s"

    def safe_run(job):  # one failed file must not stop the others; it is not written, so a rerun redoes it
        try:
            return run_one(job)
        except Exception as e:
            return f"FAILED {job[0]} {job[1]}: {type(e).__name__}: {str(e)[:120]}"

    with ThreadPoolExecutor(max_workers=a.workers) as ex:  # reads are network-bound; each thread opens its own datasets
        msgs = list(ex.map(safe_run, plan))
    for msg in msgs:
        print(msg, flush=True)
    failed = [m for m in msgs if m.startswith("FAILED")]
    if failed:
        raise SystemExit(f"{len(failed)} file(s) failed; rerun the same command to retry them")


if __name__ == "__main__":
    main()
