"""Map display layers as raster PMTiles, one file per JST date and mode.

Modes: "obs" = classes observed that day; "state" = last known state with age buckets (make_state.py).
The z18 cell grid is the z10 pixel grid (152.87 m per cell and per z10 pixel), so z10 is the native zoom
and each cell is one pixel; z9..z4 are overviews, and MapLibre overzooms past z10.
Palette PNG tiles, alpha 0 / 255 only. Overview rule: per 2x2 block the highest-priority value wins (see PRIORITY),
so a single snow cell stays visible at low zoom.

obs classes: 0 not scanned, 1 cloud, 2 shadow, 3 green, 4 snow.
state indices: 0 transparent, 1..5 green (fresh -> old), 6..10 snow (fresh -> old); see pixel.state_index.
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
from pmtiles.tile import Compression, TileType, tileid_to_zxy, zxy_to_tileid
from pmtiles.writer import write
from pyproj import Transformer
from rasterio.windows import from_bounds

# obs palette: keep in sync with docs/data/stage1.json
OBS_PALETTE = [(0, 0, 0), (235, 235, 245), (70, 50, 110), (110, 175, 110), (40, 150, 255)]
OBS_RANK = np.array([0, 2, 1, 3, 4], np.uint8)  # class -> rank (higher wins in overviews)

# state palette: green and snow, each from fresh (saturated) to old (pale)
STATE_PALETTE = [(0, 0, 0),
                 (44, 140, 62), (88, 165, 100), (140, 190, 146), (186, 212, 190), (220, 230, 222),   # green, age buckets 0..4
                 (10, 90, 235), (60, 130, 240), (112, 164, 244), (165, 197, 248), (212, 226, 251)]  # snow
STATE_RANK = np.array([0, 5, 4, 3, 2, 1, 10, 9, 8, 7, 6], np.uint8)  # snow > green, fresher > older

MIN_Z, MAX_Z = 4, 10
CANVAS_Z4 = 64  # z10 tiles per z4 tile edge


def load_day(ledger, day, cm):
    """Merge all passes of a JST day on the cellmap grid: a later clear observation wins; otherwise any scan shows.

    Returns (class, pass names)."""
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


def reduce2(a, rank=OBS_RANK):
    inverse = np.argsort(rank).astype(np.uint8)  # rank -> value (rank is a permutation of 0..n-1)
    r = rank[a]
    m = np.maximum(np.maximum(r[0::2, 0::2], r[0::2, 1::2]), np.maximum(r[1::2, 0::2], r[1::2, 1::2]))
    return inverse[m]


def png_bytes(t, palette):
    im = Image.fromarray(np.ascontiguousarray(t), "P")
    flat = [c for rgb in palette for c in rgb]
    im.putpalette(flat + [0] * (768 - len(flat)))
    b = io.BytesIO()
    im.save(b, "PNG", optimize=True, transparency=0)
    return b.getvalue()


def write_pmtiles(path, grid, cm_bounds_3857, z9_tiles, palette, rank, name, description, extra_meta):
    """Write a raster PMTiles (z4-z10) from a cell grid aligned to the cellmap mosaic."""
    tx0, ty0, tx1, ty1 = z9_tiles
    h, w = grid.shape
    x10, y10 = tx0 * 2, ty0 * 2  # z10 tile index of the mosaic origin
    cx0, cy0 = x10 // CANVAS_Z4 * CANVAS_Z4, y10 // CANVAS_Z4 * CANVAS_Z4
    nx = math.ceil((x10 + w // 256 - cx0) / CANVAS_Z4) * CANVAS_Z4
    ny = math.ceil((y10 + h // 256 - cy0) / CANVAS_Z4) * CANVAS_Z4
    canvas = np.zeros((ny * 256, nx * 256), np.uint8)
    canvas[(y10 - cy0) * 256:(y10 - cy0) * 256 + h, (x10 - cx0) * 256:(x10 - cx0) * 256 + w] = grid

    tiles, level = {}, canvas
    for z in range(MAX_Z, MIN_Z - 1, -1):
        step = 2 ** (MAX_Z - z)
        X0, Y0 = cx0 // step, cy0 // step
        for r in range(0, level.shape[0], 256):
            for c in range(0, level.shape[1], 256):
                t = level[r:r + 256, c:c + 256]
                if t.any():
                    tiles[zxy_to_tileid(z, X0 + c // 256, Y0 + r // 256)] = png_bytes(t, palette)
        if z > MIN_Z:
            level = reduce2(level, rank)

    to_ll = Transformer.from_crs(3857, 4326, always_xy=True)
    (west, north), (east, south) = to_ll.transform(cm_bounds_3857.left, cm_bounds_3857.top), to_ll.transform(cm_bounds_3857.right, cm_bounds_3857.bottom)
    e7 = lambda v: int(round(v * 1e7))
    path.parent.mkdir(parents=True, exist_ok=True)
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
            {"name": name, "description": description, "type": "overlay", "format": "png", "version": "1", **extra_meta},
        )
    return len(tiles), [west, south, east, north]


def update_dates_json(out, bbox):
    """List the dates that have files; the dashboard reads this."""
    def dates(prefix):
        return sorted(f.stem.removeprefix(prefix) for f in out.glob(f"{prefix}*.pmtiles"))
    obs, state = dates("obs-"), dates("state-")
    (out / "dates.json").write_text(json.dumps({
        "obs": obs, "state": state, "latest": (state or obs)[-1], "bbox": bbox,
        "templates": {"obs": "obs-{date}.pmtiles", "state": "state-{date}.pmtiles"},
        "palette": {"obs": ["#%02x%02x%02x" % c for c in OBS_PALETTE], "state": ["#%02x%02x%02x" % c for c in STATE_PALETTE]},
    }, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="JST date YYYY-MM-DD (observed mode)")
    ap.add_argument("--ledger", default="ledger")
    ap.add_argument("--out", default="docs/data/view")
    a = ap.parse_args()
    with rasterio.open(f"{a.ledger}/grid/cellmap.tif") as cm:
        cls, passes = load_day(a.ledger, a.date, cm)
        z9 = tuple(map(int, cm.tags()["z9_tiles"].split("/")))
        bounds = cm.bounds
    if not cls.any():
        raise SystemExit(f"no obs for {a.date}")
    out = Path(a.out)
    path = out / f"obs-{a.date}.pmtiles"
    n, bbox = write_pmtiles(path, cls, bounds, z9, OBS_PALETTE, OBS_RANK, f"snow-hokkaido obs classes {a.date} (JST)",
                            "0 not scanned, 1 cloud, 2 shadow, 3 green, 4 snow", {"passes": passes})
    update_dates_json(out, bbox)
    print(f"{path}: {n} tiles, {path.stat().st_size / 1e6:.2f} MB; passes {passes}")


if __name__ == "__main__":
    main()
