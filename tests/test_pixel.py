"""Cell ledger fold properties on synthetic observations (docs/timeseries-spec.md, section 5)."""
import random
from datetime import date, datetime, timezone

import numpy as np

from pixel import FLAG_CENSORED, STATE_GREEN, STATE_INVALID, STATE_SNOW, STATE_UNKNOWN, Obs, age_days, day_index, fold, state

UTC = timezone.utc


def obs(month, day, cls, hour=1, minute=30):
    return Obs(datetime(2026, month, day, hour, minute, tzinfo=UTC), np.array([cls], np.uint8))


def d(month, day):
    return (date(2026, month, day) - date(2026, 8, 1)).days + 1


def one(ledger, key):
    return int(ledger[key][0])


def test_day_index_uses_jst_date():
    # 2026-10-09 23:30 UTC is 2026-10-10 08:30 JST
    assert day_index(datetime(2026, 10, 9, 23, 30, tzinfo=UTC)) == d(10, 10)
    assert day_index(datetime(2026, 8, 1, 0, 0, tzinfo=UTC)) == 1
    # Jul 31 (JST) still belongs to the previous season
    assert day_index(datetime(2027, 7, 31, 1, 0, tzinfo=UTC)) == (date(2027, 7, 31) - date(2026, 8, 1)).days + 1


def test_single_snow_day_is_not_confirmed():
    led = fold([obs(10, 10, 4)])
    assert one(led, "snow_confirm_n") == 1
    assert one(led, "first_snow_day") == 0
    assert one(led, "last_clear_snow_day") == d(10, 10)


def test_two_distinct_snow_days_confirm_first_date():
    led = fold([obs(10, 10, 4), obs(10, 14, 4)])
    assert one(led, "first_snow_day") == d(10, 10)
    assert one(led, "snow_confirm_n") == 2


def test_first_snow_day_never_reset_by_later_green():
    led = fold([obs(10, 10, 4), obs(10, 12, 4), obs(10, 20, 3)])
    assert one(led, "first_snow_day") == d(10, 10)
    assert one(led, "last_clear_nosnow_day") == d(10, 20)
    assert state(led)[0] == STATE_GREEN  # state flips back, the cumulative ledger does not


def test_cloud_shadow_and_unscanned_change_nothing():
    base = fold([obs(10, 10, 3)])
    for c in (0, 1, 2):
        led = fold([obs(10, 10, 3), obs(10, 15, c)])
        assert all((led[k] == base[k]).all() for k in base)


def test_same_day_passes_count_as_one_day_latest_clear_wins():
    # green early, snow later on the same day: one snow day, state snow (no tie)
    led = fold([obs(10, 10, 3, hour=1, minute=25), obs(10, 10, 4, hour=1, minute=35)])
    assert one(led, "snow_confirm_n") == 1
    assert one(led, "last_clear_snow_day") == d(10, 10)
    assert one(led, "last_clear_nosnow_day") == 0
    assert state(led)[0] == STATE_SNOW
    # two snow passes on one day still count once
    led = fold([obs(10, 10, 4, minute=25), obs(10, 10, 4, minute=35)])
    assert one(led, "snow_confirm_n") == 1
    # a later cloudy pass does not override an earlier clear pass of the same day
    led = fold([obs(10, 10, 4, minute=25), obs(10, 10, 1, minute=35)])
    assert one(led, "last_clear_snow_day") == d(10, 10)


def test_censored_when_first_clear_observation_is_snow():
    assert fold([obs(10, 10, 1), obs(10, 12, 4)])["flags"][0] & FLAG_CENSORED
    assert not fold([obs(10, 10, 3), obs(10, 12, 4)])["flags"][0] & FLAG_CENSORED


def test_order_independent():
    seq = [obs(10, 10, 3), obs(10, 12, 4), obs(10, 12, 1, minute=40), obs(10, 15, 4), obs(10, 20, 3), obs(10, 21, 4)]
    ref = fold(seq)
    for seed in range(5):
        shuffled = seq[:]
        random.Random(seed).shuffle(shuffled)
        led = fold(shuffled)
        assert all((led[k] == ref[k]).all() for k in ref)


def test_prefix_property_ignores_later_observations():
    seq = [obs(10, 10, 3), obs(10, 12, 4), obs(10, 15, 4), obs(10, 20, 3)]
    for k in range(1, len(seq) + 1):
        upto = day_index(seq[k - 1].start_utc)
        full = fold(seq, upto_day=upto)
        prefix = fold(seq[:k])
        assert all((full[key] == prefix[key]).all() for key in prefix)


def test_state_and_age():
    led = fold([obs(10, 10, 3), obs(10, 12, 4)])
    assert state(led)[0] == STATE_SNOW
    assert age_days(led, d(10, 17))[0] == 5
    never = fold([obs(10, 10, 1)])
    assert state(never)[0] == STATE_UNKNOWN
    assert age_days(never, d(10, 17))[0] == -1


def test_invalid_cells_are_masked():
    o = Obs(datetime(2026, 10, 10, 1, 30, tzinfo=UTC), np.array([4, 4], np.uint8))
    valid = np.array([True, False])
    led = fold([o], valid=valid)
    assert led["last_clear_snow_day"].tolist() == [d(10, 10), 0]
    assert state(led, valid).tolist() == [STATE_SNOW, STATE_INVALID]


def test_folder_matches_fold_for_random_sequences():
    from pixel import Folder
    rng = np.random.default_rng(3)
    for _ in range(20):
        n_days = int(rng.integers(1, 8))
        days = sorted(rng.choice(np.arange(1, 60), n_days, replace=False).tolist())
        shape = (6,)
        per_day = {d: rng.integers(0, 5, shape).astype(np.uint8) for d in days}
        seq = [Obs(datetime(2026, 8, 1, 1, 30, tzinfo=UTC) + __import__("datetime").timedelta(days=d - 1), per_day[d]) for d in days]
        ref = fold(seq)
        f = Folder(shape)
        for d in days:
            f.update(d, per_day[d])
        led = f.ledger()
        assert all((led[k] == ref[k]).all() for k in ref)


def test_state_index_buckets_and_ordering():
    from pixel import AGE_BUCKETS, state_index
    led = fold([obs(10, 10, 3), obs(10, 12, 4)])
    today = d(10, 12)
    assert state_index(led, today)[0] == 1 + 5 + 0  # snow, fresh
    assert state_index(led, today + 3)[0] == 6 + 1  # age 3 -> second bucket
    assert state_index(led, today + 30)[0] == 6 + 4  # oldest bucket
    green = fold([obs(10, 10, 3)])
    assert state_index(green, d(10, 10))[0] == 1
    assert state_index(fold([obs(10, 10, 1)]), d(10, 10))[0] == 0  # never seen clear -> transparent
    masked = state_index(led, today, valid=np.array([False]))
    assert masked[0] == 0
