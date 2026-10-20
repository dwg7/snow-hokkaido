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


class Folder:
    """Incremental form of fold(): feed one day at a time, in ascending day order.

    update(day, day_cls) takes the per-cell class of that day, where only clear observations (3 green, 4 snow)
    matter (reduce several passes of a day to the latest clear one before calling). The result after feeding days
    1..k equals fold() over the same observations, so a saved snapshot is only a cache of this replay.
    """

    def __init__(self, shape, valid=None):
        self.active = np.ones(shape, bool) if valid is None else valid
        self.first_snow = np.zeros(shape, np.uint16)
        self.confirm = np.zeros(shape, np.uint8)
        self.last_nosnow = np.zeros(shape, np.uint16)
        self.last_snow = np.zeros(shape, np.uint16)
        self.last_any = np.zeros(shape, np.uint16)
        self.flags = np.zeros(shape, np.uint8)
        self.seen_clear = np.zeros(shape, bool)
        self.first_clear_snow_day = np.zeros(shape, np.uint16)  # first clear-snow day, kept until confirmed
        self.last_day = 0

    def update(self, day, day_cls):
        if day <= self.last_day:
            raise ValueError(f"days must ascend: {day} after {self.last_day}")
        self.last_day = day
        snow = (day_cls == CLEAR_SNOW) & self.active
        nosnow = (day_cls == CLEAR_NOSNOW) & self.active
        clear = snow | nosnow
        # censored: the cell's first clear observation in the log is snow
        self.flags[snow & ~self.seen_clear] |= FLAG_CENSORED
        self.seen_clear |= clear
        self.last_any[clear] = day
        self.last_snow[snow] = day
        self.last_nosnow[nosnow] = day
        newly_first = snow & (self.confirm == 0)
        self.first_clear_snow_day[newly_first] = day
        self.confirm[snow] = np.minimum(self.confirm[snow] + 1, 255)
        confirmed_now = snow & (self.confirm >= 2) & (self.first_snow == 0)
        self.first_snow[confirmed_now] = self.first_clear_snow_day[confirmed_now]

    def ledger(self):
        return {
            "first_snow_day": self.first_snow,
            "snow_confirm_n": self.confirm,
            "last_clear_nosnow_day": self.last_nosnow,
            "last_clear_snow_day": self.last_snow,
            "last_clear_any_day": self.last_any,
            "flags": self.flags,
        }


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
    # one observation per cell per day: the latest pass that saw the cell clear
    by_day = {}
    for o in obs:
        d = day_index(o.start_utc)
        if upto_day is not None and d > upto_day:
            continue
        cur = by_day.setdefault(d, np.zeros(shape, np.uint8))
        clear = (o.cls == CLEAR_NOSNOW) | (o.cls == CLEAR_SNOW)
        cur[clear] = o.cls[clear]  # obs are time-sorted, so later clear passes overwrite earlier ones
    folder = Folder(shape, valid)
    for d in sorted(by_day):
        folder.update(d, by_day[d])
    return folder.ledger()


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


# Display palette index of the "last known" map: 0 transparent (unknown / invalid), then state x age bucket.
AGE_BUCKETS = (1, 3, 7, 14)  # age <= 1, <= 3, <= 7, <= 14 days; older falls in the last bucket (5 buckets)
N_BUCKETS = len(AGE_BUCKETS) + 1


def state_index(ledger, today_day, valid=None):
    """uint8 per cell: 0 unknown/invalid, 1..5 green fresh->old, 6..10 snow fresh->old."""
    st = state(ledger, valid)
    age = age_days(ledger, today_day)
    bucket = np.full(age.shape, N_BUCKETS - 1, np.int32)
    for i in range(len(AGE_BUCKETS) - 1, -1, -1):
        bucket[age <= AGE_BUCKETS[i]] = i
    idx = np.zeros(st.shape, np.uint8)
    green, snow = st == STATE_GREEN, st == STATE_SNOW
    idx[green] = 1 + bucket[green]
    idx[snow] = 1 + N_BUCKETS + bucket[snow]
    return idx
