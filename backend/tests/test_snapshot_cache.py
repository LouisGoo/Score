from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from pydantic import BaseModel

from score_api.snapshots.cache import SnapshotCache


class Snapshot(BaseModel):
    version: int
    private: list[str]


def test_singleflight_merges_concurrent_requests_without_sharing_mutable_response():
    cache = SnapshotCache()
    ready, finish = Event(), Event()
    barrier = Barrier(12)
    calls = []

    def loader():
        calls.append(1)
        ready.set()
        assert finish.wait(5)
        return Snapshot(version=2, private=["a"])

    def request():
        barrier.wait()
        return cache.get(("judge", "one", 2), loader)

    with ThreadPoolExecutor(12) as pool:
        pending = [pool.submit(request) for _ in range(12)]
        assert ready.wait(5)
        finish.set()
        results = [p.result(timeout=5) for p in pending]
    assert len(calls) == 1
    results[0].private.clear()
    assert all(r.private == ["a"] for r in results[1:])


def test_cache_isolates_identity_version_ttl_bounds_and_does_not_cache_failures():
    clock = [0]
    cache = SnapshotCache(capacity=2, ttl=1, clock=lambda: clock[0])
    calls = []

    def load(name, version=1):
        calls.append(name)
        return Snapshot(version=version, private=[name])

    a = ("judge", "a", 1)
    b = ("judge", "b", 1)
    assert cache.get(a, lambda: load("a")).private == ["a"]
    assert cache.get(b, lambda: load("b")).private == ["b"]
    cache.get(a, lambda: load("wrong"))
    assert calls == ["a", "b"]
    clock[0] = 2
    cache.get(a, lambda: load("a"))
    cache.get(("judge", "a", 2), lambda: load("a", 2))
    assert len(cache.values) == 2 and calls == ["a", "b", "a", "a"]
    with pytest.raises(ValueError):
        cache.get("bad", lambda: (_ for _ in ()).throw(ValueError()))
    assert "bad" not in cache.pending
    assert cache.get("bad", lambda: load("recovered")).private == ["recovered"]
