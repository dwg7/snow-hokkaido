"""stac_search retries and gives up on a stalled response (the 2026-10-30 daily run hung on a half-read body)."""
import io
import json
import socket
import urllib.error

import pytest

pytest.importorskip("shapely")
import make_obs  # noqa: E402


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def ok(features):
    return Resp(json.dumps({"features": features}).encode())


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(make_obs.time, "sleep", lambda s: None)



def test_retries_after_timeout(monkeypatch):
    calls = []

    def fake(req, timeout):
        calls.append(1)
        if len(calls) < 3:
            raise socket.timeout("read timed out")
        return ok([{"id": "a"}])

    monkeypatch.setattr(make_obs.urllib.request, "urlopen", fake)
    assert make_obs.stac_search({}) == [{"id": "a"}]
    assert len(calls) == 3


def test_retries_after_cut_off_body(monkeypatch):
    calls = []

    def fake(req, timeout):
        calls.append(1)
        return Resp(b'{"features": [') if len(calls) == 1 else ok([])

    monkeypatch.setattr(make_obs.urllib.request, "urlopen", fake)
    assert make_obs.stac_search({}) == []
    assert len(calls) == 2


def test_gives_up_after_attempts(monkeypatch):
    calls = []

    def fake(req, timeout):
        calls.append(1)
        raise urllib.error.URLError("down")

    monkeypatch.setattr(make_obs.urllib.request, "urlopen", fake)
    with pytest.raises(urllib.error.URLError):
        make_obs.stac_search({}, attempts=3)
    assert len(calls) == 3


def test_total_time_limit(monkeypatch):
    t = iter(range(0, 1000, 100))  # each clock read jumps 100 s: the limit is hit on the first chunk
    monkeypatch.setattr(make_obs.time, "monotonic", lambda: next(t))
    monkeypatch.setattr(make_obs.urllib.request, "urlopen", lambda req, timeout: Resp(b"x" * 200000))
    with pytest.raises(TimeoutError):
        make_obs.stac_search({}, attempts=1, deadline_s=60)
