"""Time series export: alignment of per-day values, nulls for unscanned days, and the Sapporo city row."""
import pandas as pd

from export_docs import build_ts


def rows(date, items):
    out = []
    for code, (land, scanned, cloud, clear_valid, snow) in items.items():
        out.append({"muni_code": code, "date": date, "n_land": land, "n_scanned": scanned, "n_cloud": cloud,
                    "n_shadow": 0, "n_clear": clear_valid, "n_clear_canopy": 0, "n_clear_valid": clear_valid,
                    "n_snow": snow, "n_nosnow": clear_valid - snow})
    return out


def test_values_align_with_dates_and_missing_days_are_null():
    df = pd.DataFrame(rows("2026-10-01", {"01204": (100, 100, 10, 90, 9), "01457": (200, 50, 0, 50, 5)})
                      + rows("2026-10-02", {"01204": (100, 100, 20, 80, 0)}))
    ts = build_ts(df, "cloud_rate")
    assert ts["dates"] == ["2026-10-01", "2026-10-02"]
    assert ts["values"]["01204"] == [10.0, 20.0]
    assert ts["values"]["01457"] == [0.0, None]  # not scanned on the second day
    assert build_ts(df, "scan_rate")["values"]["01457"] == [25.0, None]
    assert build_ts(df, "snow_rate")["values"]["01204"] == [10.0, 0.0]  # 9 / 90, 0 / 80


def test_sapporo_city_is_the_sum_of_the_wards():
    wards = {f"011{i:02d}": (100, 100, 10, 90, 9) for i in range(1, 11)}
    ts = build_ts(pd.DataFrame(rows("2026-10-01", wards)), "snow_rate")
    assert "01100" in ts["values"] and ts["values"]["01100"] == [10.0]
    assert ts["values"]["01101"] == [10.0]  # the ward rows stay


def test_state_series_covers_every_day_and_skips_unseen_municipalities():
    from export_docs import build_state_ts
    rows_ = []
    for date, (g, sn, fresh) in {"2026-10-01": (0, 0, 0), "2026-10-02": (90, 10, 100), "2026-10-03": (90, 10, 40)}.items():
        rows_.append({"muni_code": "01204", "date": date, "n_green": g, "n_snow": sn, "n_unknown": 5, "n_invalid": 0,
                      "n_fresh": fresh, "age_median": 1.0})
    ts = build_state_ts(pd.DataFrame(rows_), "snow_rate_last")
    assert ts["dates"] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert ts["values"]["01204"] == [None, 10.0, 10.0]  # nothing seen yet on the first day
    fr = build_state_ts(pd.DataFrame(rows_), "freshness")
    assert fr["values"]["01204"] == [None, 100.0, 40.0]
