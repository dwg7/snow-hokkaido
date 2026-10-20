"""Build the map display layer for one JST day: a raster PMTiles of obs classes ("observed" mode).

The z18 cell grid is the z10 pixel grid (152.87 m per cell and per z10 pixel), so z10 is the native zoom
and each cell is one pixel; z9..z4 are overviews, and MapLibre overzooms past z10.
Palette PNG tiles, alpha 0 / 255 only. Overview rule: per 2x2 block the highest-priority class wins
(snow > green > cloud > shadow > not scanned), so a single snow cell stays visible at low zoom.

Classes: 0 not scanned, 1 cloud, 2 shadow, 3 green, 4 snow (same as obs).
"""
import argparse
import glob
import io
import json
import math
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import write
from pyproj import Transformer
from rasterio.windows import from_bounds

PALETTE = [0, 0, 0, 235, 235, 245, 70, 50, 110, 110, 175, 110, 40, 150, 255]  # keep in sync with docs/data/stage1.json
PRIORITY = np.array([0, 2, 1, 3, 4], np.uint8)  # class -> rank (higher wins in overviews)
INVERSE = np.array([0, 2, 1, 3, 4], np.uint8)  # rank -> class (the mapping is its own inverse)
MIN_Z, MAX_Z = 4, 10
CANVAS_Z4 = 64  # z10 tiles per z4 tile edge


def load_day(ledger, day, cm):
    """Merge all passes of a JST day on the cellmap grid: a later clear observation wins; otherwise any scan shows."""
    h, w = cm.shape
    cls = np.zeros((h, w), np.uint8)
    passes = {}
    for f in glob.glob(f"{ledger}/obs/season=*/{day}/*/*.tif"):
        passes.setdefault(Path(f).parent.name, []).append(f)
    order = []
    for name, files in passes.items():
        with rasterio.open(files[0]) as d:
            order.append((d.tags()["obs_start_utc"], name))
    for _, name in sorted(order):
        for f in passes[name]:
            with rasterio.open(f) as d:
                a = d.read(1)
                win = from_bounds(*d.bounds, cm.transform)
                r, c = round(win.row_off), round(win.col_off)
            cur = cls[r:r + a.shape[0], c:c + a.shape[1]]
            clear = (a == 3) | (a == 4)
            cur[clear] = a[clear]
            fill = (cur == 0) & (a != 0)
            cur[fill] = a[fill]
    return cls, sorted(passes)


def reduce2(a):
    r = PRIORITY[a]
    m = np.maximum(np.maximum(r[0::2, 0::2], r[0::2, 1::2]), np.maximum(r[1::2, 0::2], r[1::2, 1::2]))
    return INVERSE[m]


def png_bytes(t):
    im = Image.fromarray(np.ascontiguousarray(t), "P")
    im.putpalette(PALETTE + [0] * (768 - len(PALETTE)))
    b = io.BytesIO()
    im.save(b, "PNG", optimize=True, transparency=0)
    return b.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="JST date YYYY-MM-DD")
    ap.add_argument("--ledger", default="ledger")
    ap.add_argument("--out", default="docs/data/view")
    a = ap.parse_args()

    with rasterio.open(f"{a.ledger}/grid/cellmap.tif") as cm:
        cls, passes = load_day(a.ledger, a.date, cm)
        tx0, ty0, tx1, ty1 = map(int, cm.tags()["z9_tiles"].split("/"))
        h, w = cm.shape
    if not cls.any():
        raise SystemExit(f"no obs for {a.date}")

    # canvas aligned to the z4 tile grid, at z10 resolution (cells == pixels)
    x10, y10 = tx0 * 2, ty0 * 2  # z10 tile index of the mosaic origin
    cx0, cy0 = x10 // CANVAS_Z4 * CANVAS_Z4, y10 // CANVAS_Z4 * CANVAS_Z4
    nx = math.ceil((x10 + w // 256 - cx0) / CANVAS_Z4) * CANVAS_Z4
    ny = math.ceil((y10 + h // 256 - cy0) / CANVAS_Z4) * CANVAS_Z4
    canvas = np.zeros((ny * 256, nx * 256), np.uint8)
    oy, ox = (y10 - cy0) * 256, (x10 - cx0) * 256
    canvas[oy:oy + h, ox:ox + w] = cls

    tiles = {}
    level = canvas
    for z in range(MAX_Z, MIN_Z - 1, -1):
        step = 2 ** (MAX_Z - z)
        X0, Y0 = cx0 // step, cy0 // step
        for r in range(0, level.shape[0], 256):
            for c in range(0, level.shape[1], 256):
                t = level[r:r + 256, c:c + 256]
                if t.any():
                    tiles[zxy_to_tileid(z, X0 + c // 256, Y0 + r // 256)] = png_bytes(t)
        if z > MIN_Z:
            level = reduce2(level)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"obs-{a.date}.pmtiles"
    to_ll = Transformer.from_crs(3857, 4326, always_xy=True)
    with rasterio.open(f"{a.ledger}/grid/cellmap.tif") as cm:
        (west, north), (east, south) = to_ll.transform(cm.bounds.left, cm.bounds.top), to_ll.transform(cm.bounds.right, cm.bounds.bottom)
    e7 = lambda v: int(round(v * 1e7))
    with write(str(path)) as writer:
        for tid in sorted(tiles):
            writer.write_tile(tid, tiles[tid])
        writer.finalize(
            {
                "tile_type": TileType.PNG, "tile_compression": Compression.NONE,
                "min_zoom": MIN_Z, "max_zoom": MAX_Z,
                "min_lon_e7": e7(west), "min_lat_e7": e7(south), "max_lon_e7": e7(east), "max_lat_e7": e7(north),
                "center_zoom": 7, "center_lon_e7": e7((west + east) / 2), "center_lat_e7": e7((south + north) / 2),
            },
            {"name": f"snow-hokkaido obs classes {a.date} (JST)", "description": "0 not scanned, 1 cloud, 2 shadow, 3 green, 4 snow",
             "passes": passes, "type": "overlay", "format": "png", "version": "1"},
        )
    dates = sorted(f.stem.removeprefix("obs-") for f in out.glob("obs-*.pmtiles"))
    (out / "dates.json").write_text(json.dumps({"dates": dates, "latest": dates[-1], "bbox": [west, south, east, north],
                                                "template": "obs-{date}.pmtiles"}, indent=1))
    sizes = {z: sum(len(v) for k, v in tiles.items() if k_zoom(k) == z) for z in range(MIN_Z, MAX_Z + 1)}
    print(f"{path}: {len(tiles)} tiles, {path.stat().st_size / 1e6:.2f} MB; passes {passes}")
    print("bytes by zoom:", sizes)


def k_zoom(tileid):
    from pmtiles.tile import tileid_to_zxy
    return tileid_to_zxy(tileid)[0]


if __name__ == "__main__":
    main()
