"""Build grid/cellmap.tif (muni_index, static_flags) and muni/master.parquet for one z9 tile.

Assigns each z18 cell to the municipality polygon containing its center point.
Source polygons: MLIT N03 (administrative area), treated as WGS84 (JGD2011 differs by well under a cell).
"""
import argparse
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import Geod, Transformer
from rasterio.transform import from_origin
from shapely import contains_xy
from shapely.geometry import box
from shapely.ops import unary_union

Z = 18
R = 6378137.0
ORIGIN = math.pi * R
CELL_M = 2 * ORIGIN / 2**Z  # cell edge in EPSG:3857 meters


def tile_cells(z9x, z9y):
    k = 2 ** (Z - 9)
    return z9x * k, z9y * k, k  # x0, y0, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n03", required=True, help="N03 shapefile")
    ap.add_argument("--tile", default="9/459/186")
    ap.add_argument("--out", default="ledger")
    ap.add_argument("--valid-from", default="2026-01-01")
    a = ap.parse_args()

    _, tx, ty = map(int, a.tile.split("/"))
    x0, y0, n = tile_cells(tx, ty)

    xs = -ORIGIN + (x0 + np.arange(n) + 0.5) * CELL_M
    ys = ORIGIN - (y0 + np.arange(n) + 0.5) * CELL_M
    X, Y = np.meshgrid(xs, ys)
    to_ll = Transformer.from_crs(3857, 4326, always_xy=True)
    LON, LAT = to_ll.transform(X, Y)

    gdf = gpd.read_file(a.n03)
    gdf = gdf[gdf["N03_007"].notna()]
    tile_box = box(LON.min() - 0.01, LAT.min() - 0.01, LON.max() + 0.01, LAT.max() + 0.01)
    gdf = gdf[gdf.intersects(tile_box)]
    full = gdf.groupby("N03_007").agg(
        name=("N03_004", "first"),
        geometry=("geometry", lambda g: unary_union(list(g))),
    )
    full = gpd.GeoDataFrame(full, geometry="geometry", crs=gdf.crs).reset_index()

    muni_index = np.zeros((n, n), dtype=np.uint8)
    order = []
    for _, r in full.iterrows():
        inside = contains_xy(r.geometry, LON, LAT) & (muni_index == 0)
        if not inside.any():
            continue
        order.append(r)
        muni_index[inside] = len(order)
    assert len(order) < 255

    # per-row ground cell area (m2): (edge * cos(lat))^2
    row_area = (CELL_M * np.cos(np.radians(LAT[:, 0]))) ** 2
    geod = Geod(ellps="WGS84")

    rows = []
    for i, r in enumerate(order, start=1):
        m = muni_index == i
        cells = int(m.sum())
        area_cells = float((m * row_area[:, None]).sum())
        rows.append(
            dict(
                muni_index=i,
                muni_code=r.N03_007,
                name=r["name"],
                area_km2_polygon_full=abs(geod.geometry_area_perimeter(r.geometry)[0]) / 1e6,
                n_land_cells=cells,
                cell_area_m2_mean=area_cells / cells,
                area_km2_cells=area_cells / 1e6,
                valid_from=a.valid_from,
                valid_to=None,
                tabular_row=None,
                tabular_col=None,
            )
        )
    master = pd.DataFrame(rows)

    # polygon area clipped to the tile's cell extent (geodesic), for comparison with cell area
    west = -ORIGIN + x0 * CELL_M
    east = -ORIGIN + (x0 + n) * CELL_M
    north = ORIGIN - y0 * CELL_M
    south = ORIGIN - (y0 + n) * CELL_M
    ext = gpd.GeoSeries([box(west, south, east, north)], crs=3857).to_crs(4326).iloc[0]
    clip = {r.N03_007: abs(geod.geometry_area_perimeter(r.geometry.intersection(ext))[0]) / 1e6 for r in order}
    master["area_km2_polygon_in_tile"] = master["muni_code"].map(clip)
    master["diff_pct"] = 100 * (master["area_km2_cells"] / master["area_km2_polygon_in_tile"] - 1)

    out = Path(a.out)
    (out / "grid").mkdir(parents=True, exist_ok=True)
    (out / "muni").mkdir(parents=True, exist_ok=True)

    # N03 has no sea/water polygons: static_flags bit2 (sea) = outside every municipality.
    # bit0 (evergreen) and bit1 (lake) have no source yet (D3, D4) and stay 0.
    flags = np.where(muni_index == 0, 4, 0).astype(np.uint8)

    prof = dict(
        driver="COG", width=n, height=n, count=2, dtype="uint8", crs="EPSG:3857",
        transform=from_origin(west, north, CELL_M, CELL_M), compress="deflate",
    )
    with rasterio.open(out / "grid" / "cellmap.tif", "w", **prof) as dst:
        dst.write(muni_index, 1)
        dst.write(flags, 2)
        dst.set_band_description(1, "muni_index")
        dst.set_band_description(2, "static_flags")
        dst.update_tags(
            tile=a.tile, zoom=str(Z), source="MLIT N03", source_version=a.valid_from,
            rule="cell center point-in-polygon, first match wins", elev_m="not yet",
        )
    master.to_parquet(out / "muni" / "master.parquet", index=False)
    print(master.round(3).to_string())
    print("cells outside any municipality:", int((muni_index == 0).sum()))


if __name__ == "__main__":
    main()
