"""Cell ledger fold: a pure function of the obs log (see docs/timeseries-spec.md, section 5).

obs classes: 0 not scanned, 1 cloud, 2 shadow, 3 green (clear, no snow), 4 snow.
Day indices are 1-based days since the season start (Aug 1, JST); 0 means "never".
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import numpy as np

JST = timezone(timedelta(hours=9))
FLAG_CENSORED = 1
CLEAR_NOSNOW, CLEAR_SNOW = 3, 4

STATE_UNKNOWN, STATE_GREEN, STATE_SNOW, STATE_INVALID = 0, 1, 2, 3


@dataclass(frozen=True)
class Obs:
    start_utc: datetime  # tz-aware
    cls: np.ndarray  # (h, w) uint8 class per cell


def season_start(d: date) -> date:
    return date(d.year if d.month >= 8 else d.year - 1, 8, 1)


def day_index(start_utc: datetime) -> int:
    """1-based day number of the JST date of an observation within its season."""
    d = start_utc.astimezone(JST).date()
    return (d - season_start(d)).days + 1


def fold(obs, upto_day=None, valid=None):
    """Fold observations into per-cell ledger arrays.

    obs: iterable of Obs (any order). upto_day: ignore observations of later days.
    valid: optional bool array; False cells (masked in cellmap) are left at their initial values.
    Returns dict of arrays: first_snow_day, snow_confirm_n, last_clear_nosnow_day,
    last_clear_snow_day, last_clear_any_day, flags.
    """
    obs = sorted(obs, key=lambda o: o.start_utc)
    if not obs:
        raise ValueError("fold needs at least one observation to know the grid shape")
    shape = obs[0].cls.shape
    first_snow = np.zeros(shape, np.uint16)
    confirm = np.zeros(shape, np.uint8)
    last_nosnow = np.zeros(shape, np.uint16)
    last_snow = np.zeros(shape, np.uint16)
    last_any = np.zeros(shape, np.uint16)
    flags = np.zeros(shape, np.uint8)
    seen_clear = np.zeros(shape, bool)
    snow_days_first = np.zeros(shape, np.uint16)  # first clear-snow day, kept until confirmed

    # one observation per cell per day: the latest pass that saw the cell clear
    by_day = {}
    for o in obs:
        d = day_index(o.start_utc)
        if upto_day is not None and d > upto_day:
            continue
        cur = by_day.setdefault(d, np.zeros(shape, np.uint8))
        clear = (o.cls == CLEAR_NOSNOW) | (o.cls == CLEAR_SNOW)
        cur[clear] = o.cls[clear]  # obs are time-sorted, so later clear passes overwrite earlier ones

    active = np.ones(shape, bool) if valid is None else valid
    for d in sorted(by_day):
        day_cls = by_day[d]
        snow = (day_cls == CLEAR_SNOW) & active
        nosnow = (day_cls == CLEAR_NOSNOW) & active
        clear = snow | nosnow
        # censored: the cell's first clear observation in the log is snow
        flags[snow & ~seen_clear] |= FLAG_CENSORED
        seen_clear |= clear
        last_any[clear] = d
        last_snow[snow] = d
        last_nosnow[nosnow] = d
        newly_first = snow & (confirm == 0)
        snow_days_first[newly_first] = d
        confirm[snow] = np.minimum(confirm[snow] + 1, 255)
        confirmed_now = snow & (confirm >= 2) & (first_snow == 0)
        first_snow[confirmed_now] = snow_days_first[confirmed_now]

    return {
        "first_snow_day": first_snow,
        "snow_confirm_n": confirm,
        "last_clear_nosnow_day": last_nosnow,
        "last_clear_snow_day": last_snow,
        "last_clear_any_day": last_any,
        "flags": flags,
    }


def state(ledger, valid=None):
    """Derived state per cell: unknown / green / snow / invalid (not stored)."""
    snow, nosnow = ledger["last_clear_snow_day"], ledger["last_clear_nosnow_day"]
    out = np.full(snow.shape, STATE_UNKNOWN, np.uint8)
    out[(snow > 0) | (nosnow > 0)] = STATE_GREEN
    out[snow > nosnow] = STATE_SNOW
    if valid is not None:
        out[~valid] = STATE_INVALID
    return out


def age_days(ledger, today_day):
    """Days since the cell was last seen clear; -1 where never seen."""
    last = ledger["last_clear_any_day"].astype(np.int32)
    return np.where(last > 0, today_day - last, -1)
