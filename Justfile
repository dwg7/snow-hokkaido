# Stage-1 tile; override with `just tile=9/459/187 cellmap`
tile := "9/459/186"
deps := "--with geopandas --with pyogrio --with shapely --with pyproj --with rasterio --with pandas --with pyarrow --with numpy"

cellmap:
    uv run {{deps}} python src/make_cellmap.py --n03 data/raw/n03-20260101/N03-20260101_01.shp

obs date *args:
    uv run --with rasterio --with numpy --with pyproj --with shapely python src/make_obs.py --date {{date}} {{args}}

events +obs:
    uv run --with rasterio --with numpy --with pandas --with pyarrow python src/make_events.py --obs {{obs}}

test:
    uv run --with pytest --with rasterio --with numpy --with pandas --with pyarrow pytest -q

docs-data:
    uv run {{deps}} --with pillow python src/export_docs.py
