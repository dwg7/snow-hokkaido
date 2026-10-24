# Stage-1 tile; override with `just tile=9/459/187 cellmap`
tile := "9/459/186"
deps := "--with geopandas --with pyogrio --with shapely --with pyproj --with rasterio --with pandas --with pyarrow --with numpy"

# Download MLIT N03 (administrative areas, 2026-01-01) for `just cellmap`. Not redistributed by this repository.
fetch-n03:
    mkdir -p data/raw/n03-20260101
    curl -sSfL -o data/raw/n03-20260101.zip https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2026/N03-20260101_01_GML.zip
    unzip -q -o data/raw/n03-20260101.zip -d data/raw/n03-20260101

cellmap:
    uv run {{deps}} python src/make_cellmap.py --n03 data/raw/n03-20260101/N03-20260101_01.shp

obs date *args:
    uv run --with rasterio --with numpy --with pyproj --with shapely python src/make_obs.py --date {{date}} {{args}}

events +obs:
    uv run --with rasterio --with numpy --with pandas --with pyarrow python src/make_events.py --obs {{obs}}

test:
    uv run --with pytest --with rasterio --with numpy --with pandas --with pyarrow --with pmtiles --with pillow --with pyproj pytest -q

docs-data:
    uv run --with pandas --with pyarrow python src/export_docs.py

view-tiles date:
    uv run --with rasterio --with numpy --with pyproj --with pillow --with pmtiles python src/make_view_tiles.py --date {{date}}

state upto *args:
    uv run --with rasterio --with numpy --with pandas --with pyarrow --with pyproj --with pillow --with pmtiles python src/make_state.py --upto {{upto}} {{args}}

# Build the staging directory for Source Cooperative and print the plan (dry run). Add --upload to really sync.
publish *args:
    uv run --with rasterio --with numpy python src/publish.py {{args}}

# Process every JST day from `newest` back to `oldest`, newest first (so the latest days fill in first). Resumable.
obs-range newest oldest *args:
    #!/usr/bin/env bash
    set -euo pipefail
    d="{{newest}}"; fail=0
    while [[ ! "$d" < "{{oldest}}" ]]; do
      echo "=== $d"; just obs "$d" {{args}} || fail=1
      d=$(date -j -v-1d -f %Y-%m-%d "$d" +%Y-%m-%d)
    done
    exit $fail

# After obs files exist: events for every pass that has none, the state history up to `upto`, the display tiles, and the Pages data.
rebuild upto:
    #!/usr/bin/env bash
    set -euo pipefail
    for p in ledger/obs/season=*/*/*; do
      [ -d "$p" ] || continue
      day=$(basename "$(dirname "$p")"); dt=$(basename "$p")
      f=$(ls ledger/events/season=*/part-${day}_${dt}.parquet 2>/dev/null | head -1 || true)
      if [ -z "$f" ]; then echo "events: $p"; just events "$p" > /dev/null; fi
    done
    just state {{upto}}
    for d in $(ls ledger/obs/season=*/ | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' | sort -u); do just view-tiles "$d" > /dev/null; done
    just docs-data
    just test

# One daily run: new obs (today and the previous days), events, state, display files, publish plan. Add --upload after `source-coop login`.
daily *args:
    python3 src/daily.py {{args}}
