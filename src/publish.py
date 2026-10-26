"""Stage the files for Source Cooperative and (only with --upload) sync them.

Layout (docs/storage.md; decisions of the owner):
  obs/season=YYYY/<JST date>/<datatake_id>.tif   obs-lite: one COG per pass, class + clear_pct, whole cellmap extent
  events/season=YYYY/part-*.parquet
  derived/state/season=YYYY.parquet
  pixel/season=YYYY/latest.tif                   latest cell ledger only (a cache; replay needs obs-lite)
  view/obs-<date>.pmtiles, view/state-<date>.pmtiles, view/dates.json
  series/*.json, stage1.json                      what the dashboard reads every day (docs/data/series, docs/data/stage1.json)

Not published: municipality boundary geometry and anything rasterized from it (grid/cellmap.tif, muni/master.parquet);
users fetch N03 themselves (`just fetch-n03`, `just cellmap`).

Default is a dry run that builds the staging directory and prints what would be uploaded. --upload runs
`aws s3 sync` against --dest with the credentials already configured in your environment; this script never reads keys.
"""
import argparse
import glob
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import from_bounds


def build_obs_lite(ledger, staging, days=None):
    """One COG per pass: mosaic the pass's z9 tile files onto the cellmap grid, keep class and clear_pct."""
    with rasterio.open(f"{ledger}/grid/cellmap.tif") as cm:
        h, w, tf, crs = cm.height, cm.width, cm.transform, cm.crs
        bounds = cm.bounds
    passes = defaultdict(list)
    for f in sorted(glob.glob(f"{ledger}/obs/season=*/*/*/*.tif")):
        p = Path(f)
        if days and p.parts[-3] not in days:
            continue
        passes[(p.parts[-4], p.parts[-3], p.parent.name)].append(f)  # season=, JST date, datatake
    out = []
    for (season, day, datatake), files in sorted(passes.items()):
        dst_path = staging / "obs" / season / day / f"{datatake}.tif"
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if dst_path.exists() and dst_path.stat().st_mtime >= max(Path(f).stat().st_mtime for f in files):
            out.append(dst_path)  # up to date: keep the file (and its mtime) so `aws s3 sync` does not re-upload it
            continue
        cls = np.zeros((h, w), np.uint8)
        pct = np.zeros((h, w), np.uint8)
        tags = {}
        scenes, starts, ends = [], [], []
        for f in files:
            with rasterio.open(f) as d:
                win = from_bounds(*d.bounds, tf)
                r, c = round(win.row_off), round(win.col_off)
                cls[r:r + d.height, c:c + d.width] = d.read(1)
                pct[r:r + d.height, c:c + d.width] = d.read(2)
                t = d.tags()
                tags = tags or t
                scenes += t["scene"].split(","); starts.append(t["obs_start_utc"]); ends.append(t["obs_end_utc"])
        prof = dict(driver="COG", width=w, height=h, count=2, dtype="uint8", crs=crs, transform=tf,
                    compress="deflate", blocksize=256, overview_resampling="mode")
        with rasterio.open(dst_path, "w", **prof) as dst:
            dst.write(cls, 1)
            dst.write(pct, 2)
            dst.set_band_description(1, "class")
            dst.set_band_description(2, "clear_pct")
            dst.update_tags(
                sensor=tags["sensor"], stac_collection=tags["stac_collection"], datatake_id=datatake,
                scene=",".join(sorted(set(scenes))), obs_start_utc=min(starts), obs_end_utc=max(ends),
                algo_version=tags["algo_version"], snow_source=tags.get("snow_source", ""),
                classes="0 not scanned, 1 cloud, 2 shadow, 3 green (clear, no snow), 4 snow",
                note="obs-lite: z9 tile files are merged onto the cellmap grid (EPSG:3857, z18 cells)",
                attribution="Contains modified Copernicus Sentinel data (Sentinel-2 L2A via Earth Search)",
            )
        out.append(dst_path)
    return out


def copy_plain(ledger, staging, docs):
    files = []
    for pattern, dest in (
        (f"{ledger}/events/season=*/*.parquet", "events"),
        (f"{ledger}/derived/state/*.parquet", "derived/state"),
        (f"{ledger}/derived/daily/*.parquet", "derived/daily"),
    ):
        for f in sorted(glob.glob(pattern)):
            rel = Path(f).relative_to(ledger)
            t = staging / rel
            t.parent.mkdir(parents=True, exist_ok=True)
            if not t.exists() or Path(f).stat().st_mtime > t.stat().st_mtime or Path(f).stat().st_size != t.stat().st_size:
                shutil.copy2(f, t)
            files.append(t)
    # latest pixel only
    pix = sorted(glob.glob(f"{ledger}/pixel/season=*/*.tif"))
    if pix:
        latest = Path(pix[-1])
        t = staging / "pixel" / latest.parent.name / "latest.tif"
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(latest, t)  # always replaced: its content changes every day
        files.append(t)
    # the small files the dashboard reads every day (series for the tabular maps, the legend meta): next to view/, so a daily
    # run needs no commit and no Pages rebuild (the copies in docs/data/ stay as the page's fallback)
    for f in sorted(glob.glob(f"{docs}/data/series/*.json")) + [f"{docs}/data/stage1.json"]:
        rel = Path(f).relative_to(f"{docs}/data")
        t = staging / rel
        t.parent.mkdir(parents=True, exist_ok=True)
        if not t.exists() or Path(f).stat().st_mtime > t.stat().st_mtime or Path(f).stat().st_size != t.stat().st_size:
            shutil.copy2(f, t)
        files.append(t)
    for f in sorted(glob.glob(f"{docs}/data/view/*")):
        t = staging / "view" / Path(f).name
        t.parent.mkdir(parents=True, exist_ok=True)
        if not t.exists() or Path(f).stat().st_mtime > t.stat().st_mtime or Path(f).stat().st_size != t.stat().st_size:
            shutil.copy2(f, t)
        files.append(t)
    return files


DATA_README = '''# snow-hokkaido data

Daily, cloud-aware snow-cover records for Hokkaido, built from Sentinel-2 L2A on a z18 XYZ-tile cell grid
(112 m cells). Code, documentation and the dashboard: https://github.com/dwg7/snow-hokkaido

## Layout

- `obs/season=YYYY/<JST date>/<datatake_id>.tif`  obs-lite, one COG per pass: band 1 class (0 not scanned, 1 cloud,
  2 shadow, 3 green = clear and no snow, 4 snow), band 2 clear_pct. EPSG:3857, z18 cells, 7168 x 4608 cells
  (z9 tiles x 454..467, y 183..191). Not every pass covers all of Hokkaido: uncovered cells are 0.
- `events/`  per municipality and pass: counts of cells by class (Parquet)
- `derived/state/`  per municipality and date: last-known state counts (Parquet)
- `derived/daily/`  per municipality and observed day: counts of that day's observation (one observation per cell per day; same columns as events)
- `pixel/season=YYYY/latest.tif`  latest cell ledger (6 bands, uint16); a cache that can be rebuilt from `obs`
- `view/`  raster PMTiles for the dashboard (z4-z10; a z10 pixel is a cell) and `dates.json`

Municipality boundary geometry is not included. Rebuild the cell-to-municipality map yourself (`just fetch-n03`,
`just cellmap` in the repository).

## License and attribution

CC BY 4.0. Please credit:

- Contains modified Copernicus Sentinel data 2026 (Sentinel-2 L2A, via Earth Search by Element 84).
- Municipality codes and aggregation use 「国土数値情報(行政区域データ)」(国土交通省)
  (https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2026.html) as the basis; the data were processed
  (assignment to cells, aggregation). This is not a product made by the national government.
- Snow classes are provisional (algorithm version in each file's tags); see the repository's `docs/stage1-checks.md`
  for what was and was not verified.
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default="ledger")
    ap.add_argument("--docs", default="docs")
    ap.add_argument("--staging", default="publish")
    ap.add_argument("--dest", default="s3://smartmaps/foil4gr1/snow-hokkaido/", help="S3 destination prefix (check before --upload)")
    ap.add_argument("--profile", default="source-coop", help="AWS CLI profile (its credential_process and endpoint_url are used)")
    ap.add_argument("--endpoint", default="https://data.source.coop", help="S3 endpoint URL")
    ap.add_argument("--days", help="comma-separated JST dates to include in obs-lite (default: all); use it to skip days still being processed")
    ap.add_argument("--upload", action="store_true", help="really upload (default: dry run)")
    a = ap.parse_args()

    staging = Path(a.staging)  # kept between runs; only changed files are rebuilt or copied
    staging.mkdir(parents=True, exist_ok=True)
    files = build_obs_lite(a.ledger, staging, set(a.days.split(",")) if a.days else None) + copy_plain(a.ledger, staging, a.docs)
    (staging / "README.md").write_text(DATA_README)
    files.append(staging / "README.md")

    by_kind = defaultdict(lambda: [0, 0])
    for f in files:
        k = f.relative_to(staging).parts[0]
        by_kind[k][0] += 1
        by_kind[k][1] += f.stat().st_size
    print(f"staged in {staging}/ :")
    for k, (n, b) in sorted(by_kind.items()):
        print(f"  {k:10s} {n:4d} files {b / 1e6:7.2f} MB")
    print(f"  total      {len(files):4d} files {sum(f.stat().st_size for f in files) / 1e6:7.2f} MB")
    cmd = ["aws", "s3", "sync", str(staging) + "/", a.dest, "--profile", a.profile, "--endpoint-url", a.endpoint]
    if not a.upload:
        print("\nDRY RUN. Would run:", " ".join(cmd))
        return
    print("running:", " ".join(cmd))
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
