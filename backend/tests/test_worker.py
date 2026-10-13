from types import SimpleNamespace

from sqlalchemy.exc import OperationalError

from score_api.worker import Batch, run_loop


def test_backoff_recovers_and_stops_without_busy_loop():
    results = iter(
        [
            Batch(0, 0, 0),
            OperationalError("hidden", {}, Exception()),
            Batch(1, 0, 1),
            Batch(50, 50, 0),
            Batch(0, 0, 0),
        ]
    )
    waits = []

    def scan():
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    stop = SimpleNamespace(is_set=lambda: len(waits) == 5, wait=waits.append)
    run_loop(SimpleNamespace(run_once=scan), stop, minimum=1, maximum=4, jitter=lambda a, b: b)
    assert waits == [2, 4, 4, 1, 2]
