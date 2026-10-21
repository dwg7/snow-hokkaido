"""Re-derive existing obs files under algo-v1-dev3 without reading imagery again.

Rule change dev2 -> dev3: a snow cell needs clear_pct >= SNOW_MIN_CLEAR_PCT; otherwise it is "not seen".
The old files do not keep the per-class pixel counts of the other pixels, so a dropped snow cell becomes
class 1 (cloud); a rebuild from imagery (`just obs <date> --force`) would pick the most frequent of
no data / cloud / shadow instead. The file is rewritten in place; keep a copy of the old tree first.
"""
import argparse
import glob

import numpy as np
import rasterio

from make_obs import ALGO_VERSION, SNOW_MIN_CLEAR_PCT


def migrate(path):
    with rasterio.open(path) as d:
        tags, prof = d.tags(), d.profile
        cls, ndsi_q, pct = d.read(1), d.read(2), d.read(3)
        names = d.descriptions
    if tags.get("algo_version") == ALGO_VERSION:
        return 0
    drop = (cls == 4) & (pct < SNOW_MIN_CLEAR_PCT)
    cls = np.where(drop, 1, cls).astype(np.uint8)
    prof.update(driver="COG", compress="deflate")
    for k in ("blockxsize", "blockysize", "tiled", "interleave"):
        prof.pop(k, None)
    tags.update(algo_version=ALGO_VERSION, snow_min_clear_pct=str(SNOW_MIN_CLEAR_PCT), migrated_from=tags["algo_version"],
                migration_note=f"{int(drop.sum())} snow cells with clear_pct < {SNOW_MIN_CLEAR_PCT} set to class 1 without re-reading imagery")
    with rasterio.open(path, "w", **prof) as dst:
        for i, (arr, name) in enumerate([(cls, names[0]), (ndsi_q, names[1]), (pct, names[2])], 1):
            dst.write(arr, i)
            dst.set_band_description(i, name)
        dst.update_tags(**tags)
    return int(drop.sum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default="ledger")
    a = ap.parse_args()
    files = sorted(glob.glob(f"{a.ledger}/obs/season=*/*/*/*.tif"))
    total = sum(migrate(f) for f in files)
    print(f"{len(files)} files; {total} snow cells set to cloud")


if __name__ == "__main__":
    main()
