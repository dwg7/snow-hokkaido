"""Display layer: overview priority rule, and that the PMTiles z10 pixels are the obs cells (alignment)."""
import glob
import io
import os

import numpy as np
import pytest

from make_view_tiles import reduce2


def test_overview_priority_snow_wins_then_green_cloud_shadow():
    a = np.array([[4, 3], [1, 2]], np.uint8)
    assert reduce2(np.pad(a, ((0, 0), (0, 0))))[0, 0] == 4  # snow beats everything
    assert reduce2(np.array([[3, 1], [2, 0]], np.uint8))[0, 0] == 3  # green beats cloud, shadow
    assert reduce2(np.array([[1, 2], [0, 0]], np.uint8))[0, 0] == 1  # cloud beats shadow
    assert reduce2(np.zeros((2, 2), np.uint8))[0, 0] == 0


def test_pmtiles_z10_pixels_equal_obs_cells():
    pm = glob.glob("docs/data/view/obs-*.pmtiles")
    obs = glob.glob("ledger/obs/season=*/*/*/459-186.tif")
    if not pm or not obs:
        pytest.skip("no view tiles or obs in this checkout")
    import rasterio
    from PIL import Image
    from pmtiles.reader import MmapSource, Reader

    day = os.path.basename(pm[0])[4:-8]
    mine = [f for f in obs if f"/{day}/" in f]
    if not mine:
        pytest.skip("obs for that day not present (obs is git-ignored)")
    cells = rasterio.open(mine[0]).read(1)
    with open(pm[0], "rb") as fh:
        reader = Reader(MmapSource(fh))
        for dy in (0, 1):
            for dx in (0, 1):
                data = reader.get(10, 918 + dx, 372 + dy)  # z9 tile 459/186 = four z10 tiles
                block = cells[dy * 256:(dy + 1) * 256, dx * 256:(dx + 1) * 256]
                if data is None:
                    assert not block.any()
                else:
                    assert np.array_equal(np.array(Image.open(io.BytesIO(data))), block)
