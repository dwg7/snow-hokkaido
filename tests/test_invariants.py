"""Ledger invariants (HANDOFF appendix A). Synthetic cases run anywhere; ledger cases skip when data is absent."""
import glob

import numpy as np
import pandas as pd
import pytest

from make_events import build_events


def check_invariants(df):
    assert (df.n_scanned <= df.n_land).all()
    assert (df.n_scanned == df.n_cloud + df.n_shadow + df.n_clear).all()
    assert (df.n_clear == df.n_clear_canopy + df.n_clear_valid).all()
    assert (df.n_clear_valid == df.n_snow + df.n_marginal + df.n_nosnow).all()


def synthetic():
    n = 8
    rng = np.random.default_rng(0)
    cls = rng.integers(0, 5, (n, n)).astype(np.uint8)
    ndsi_q = rng.integers(0, 200, (n, n)).astype(np.uint8)
    muni = np.zeros((n, n), np.uint8)
    muni[:, :4] = 1
    muni[:, 4:7] = 2  # last column stays outside every municipality
    flags = np.zeros((n, n), np.uint8)
    flags[0, :] |= 1  # canopy
    flags[1, 1] |= 2  # lake
    flags[2, 5] |= 4  # sea
    master = pd.DataFrame({"muni_index": [1, 2], "muni_code": ["00001", "00002"]})
    return cls, ndsi_q, muni, flags, master


def test_synthetic_invariants():
    cls, ndsi_q, muni, flags, master = synthetic()
    df = build_events(cls, ndsi_q, muni, flags, master, {})
    check_invariants(df)
    assert df.n_land.sum() == int(((muni > 0) & ((flags & 6) == 0)).sum())


def test_synthetic_snow_marginal_split():
    cls = np.full((2, 2), 4, np.uint8)
    ndsi_q = np.array([[142, 180], [150, 100]], np.uint8)  # NDSI 0.42, 0.80, 0.50, 0.00
    muni = np.ones((2, 2), np.uint8)
    flags = np.zeros((2, 2), np.uint8)
    master = pd.DataFrame({"muni_index": [1], "muni_code": ["00001"]})
    df = build_events(cls, ndsi_q, muni, flags, master, {}).iloc[0]
    assert (df.n_marginal, df.n_snow, df.n_nosnow) == (1, 3, 0)


@pytest.mark.parametrize("path", glob.glob("ledger/events/season=*/part-*.parquet"))
def test_ledger_events_invariants(path):
    check_invariants(pd.read_parquet(path))


def test_ledger_land_matches_master():
    files = glob.glob("ledger/events/season=*/part-*.parquet")
    if not files:
        pytest.skip("no events")
    master = pd.read_parquet("ledger/muni/master.parquet").set_index("muni_code")
    for f in files:
        df = pd.read_parquet(f).set_index("muni_code")
        assert (df.n_land == master.loc[df.index, "n_land_cells"]).all()
