"""derived/state rows: the stored-count invariant (HANDOFF appendix A) on synthetic grids."""
from datetime import date

import numpy as np
import pandas as pd

from make_state import muni_rows
from pixel import Folder


def test_muni_rows_invariant_and_freshness():
    shape = (4, 4)
    muni = np.zeros(shape, np.uint8)
    muni[:, :2] = 1
    muni[:, 2:3] = 2  # last column outside every municipality (sea)
    flags = np.zeros(shape, np.uint8)
    flags[0, 0] = 2  # lake: not land
    flags[1, 0] = 1  # canopy: land but invalid
    land = (muni > 0) & ((flags & 6) == 0)
    valid = land & ((flags & 1) == 0)
    f = Folder(shape, valid)
    day1 = np.zeros(shape, np.uint8); day1[2, :2] = 4; day1[3, :2] = 3; day1[0, 2] = 3
    f.update(10, day1)
    master = pd.DataFrame({"muni_index": [1, 2], "muni_code": ["00001", "00002"]})
    df = muni_rows(date(2026, 10, 30), 30, f.ledger(), muni, land, valid, master, 3).set_index("muni_code")
    n_land = pd.Series({"00001": int(land[muni == 1].sum()), "00002": int(land[muni == 2].sum())})
    total = df.n_green + df.n_snow + df.n_unknown + df.n_invalid
    assert (total == n_land).all()
    assert df.loc["00001", "n_snow"] == 2 and df.loc["00001", "n_green"] == 2
    assert df.loc["00001", "n_invalid"] == 1  # the canopy cell
    assert df.loc["00001", "n_fresh"] == 0  # last seen 20 days ago (> 7)
    assert df.loc["00001", "age_median"] == 20
