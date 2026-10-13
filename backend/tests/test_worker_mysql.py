from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from sqlalchemy import select
from test_ballots_mysql import put
from test_ballots_mysql import scoring as scoring
from test_results_mysql import act, history

from score_api.db import Database
from score_api.events.models import Event, EventAudit
from score_api.results.models import ResultSnapshot
from score_api.rounds.models import ScoringRound
from score_api.worker import DeadlineWorker, close_due

pytestmark = pytest.mark.mysql


def test_deadline_excludes_pause_unlimited_and_preserves_cutoff(scoring, clients, event_db):
    db, _ = event_db
    rid = scoring[0]["rounds"][0]["id"]
    at = scoring[2] + timedelta(seconds=60)
    worker = DeadlineWorker(db, clock=lambda: at - timedelta(microseconds=1))
    assert worker.run_once().scanned == 0
    scoring[1][0].app.state.clock = lambda: at
    assert put(scoring).json()["error"]["code"] == "DEADLINE_EXCEEDED"
    assert history(clients[0], rid) == []  # worker 延迟不延长提交窗口
    assert act(clients[0], rid, "pause").status_code == 200
    worker.clock = lambda: at + timedelta(days=1)
    assert worker.run_once().scanned == 0
    assert act(clients[0], rid, "close", reason="重新配置窗口").status_code == 200
    assert (
        act(clients[0], rid, "reopen", reason="不限时补评", duration_seconds=None).status_code
        == 200
    )
    assert worker.run_once().scanned == 0


def test_multiple_workers_close_once_and_restart(scoring, clients, event_db, mysql_settings):
    db, _ = event_db
    rid = scoring[0]["rounds"][0]["id"]
    assert put(scoring).status_code == 200
    at = scoring[2] + timedelta(seconds=60)
    gate = Barrier(2)

    def process():
        other_db = Database(mysql_settings, role="worker")
        try:
            gate.wait()
            return DeadlineWorker(other_db, clock=lambda: at).run_once()
        finally:
            assert other_db.engine.pool.checkedout() == 0
            other_db.dispose()

    with ThreadPoolExecutor(2) as pool:
        first, second = pool.submit(process), pool.submit(process)
        assert first.result().closed + second.result().closed == 1
    saved = history(clients[0], rid)
    assert len(saved) == 1 and saved[0]["source"] == "deadline"
    assert saved[0]["calculation"]["valid_count"] == 1
    with db.transaction() as session:
        logs = list(
            session.scalars(
                select(EventAudit).where(
                    EventAudit.event_id == scoring[0]["event"]["id"],
                    EventAudit.action == "round.closed",
                )
            )
        )
        assert len(logs) == 1 and logs[0].actor_id is None
    assert DeadlineWorker(db, clock=lambda: at).run_once().closed == 0
    assert act(clients[0], rid, "reopen", reason="补评", duration_seconds=1).status_code == 200
    assert DeadlineWorker(db, clock=lambda: at).run_once().closed == 1
    assert len(history(clients[0], rid)) == 2


def test_busy_event_skipped_and_retried(scoring, event_db):
    db, _ = event_db
    event_id = scoring[0]["event"]["id"]
    rid = scoring[0]["rounds"][0]["id"]
    at = scoring[2] + timedelta(seconds=60)
    with db.transaction() as session:
        session.scalar(select(Event).where(Event.id == event_id).with_for_update())
        assert not close_due(db, event_id, rid, lambda: at)
    assert close_due(db, event_id, rid, lambda: at)


def test_failure_rollback_retry_and_keyset_does_not_starve(scoring, event_db, monkeypatch):
    from score_api import worker as module

    db, _ = event_db
    rid = scoring[0]["rounds"][0]["id"]
    worker = DeadlineWorker(db, batch_size=1, clock=lambda: scoring[2] + timedelta(seconds=60))
    original = module.freeze_result

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected after flush")

    monkeypatch.setattr(module, "freeze_result", fail)
    assert worker.run_once().failed == 1
    with db.transaction() as session:
        assert session.get(ScoringRound, rid).status == "OPEN"
        assert session.scalar(select(ResultSnapshot).where(ResultSnapshot.round_id == rid)) is None
    monkeypatch.setattr(module, "freeze_result", original)
    assert worker.run_once().scanned == 0  # 页尾重置游标
    assert worker.run_once().closed == 1
