from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy import select
from test_ballots_mysql import payload, put
from test_ballots_mysql import scoring as scoring
from test_rounds_mysql import control

from score_api.events.models import EventAudit
from score_api.outbox.models import OutboxEvent
from score_api.results.models import ResultSnapshot
from score_api.results.service import scoring_rule
from score_api.scoring import Ballot, aggregate

pytestmark = pytest.mark.mysql


def act(owner, round_id, action, **extra):
    if action == "publish":
        action = "publish-result"
    current = owner.get(f"/api/v1/rounds/{round_id}").json()
    return owner.post(
        f"/api/v1/rounds/{round_id}/{action}",
        json={"expected_version": current["version"], **extra},
    )


def history(owner, round_id):
    response = owner.get(f"/api/v1/rounds/{round_id}/results")
    assert response.status_code == 200, response.text
    return response.json()["snapshots"]


def event_action(owner, event_id, action):
    version = owner.get(f"/api/v1/events/{event_id}").json()["version"]
    return owner.post(f"/api/v1/events/{event_id}/{action}", json={"expected_version": version})


def test_close_reopen_publish_freezes_and_finish(scoring, clients, event_db):
    owner, other = clients
    event_id = scoring[0]["event"]["id"]
    rid = scoring[0]["rounds"][0]["id"]
    key = str(uuid4())
    receipt = put(scoring, key=key).json()
    assert act(owner, rid, "close").json()["error"]["code"] == "CLOSE_REASON_REQUIRED"
    assert act(owner, rid, "close", reason="一位缺席").status_code == 200
    first = history(owner, rid)[0]
    assert first["calculation"]["final_score"] is None
    assert len(first["calculation"]["missing_judge_ids"]) == 1
    assert act(owner, rid, "publish").json()["error"]["code"] == "INSUFFICIENT_BALLOTS"
    assert other.get(f"/api/v1/rounds/{rid}/results").status_code == 404
    assert scoring[1][0].get(f"/api/v1/rounds/{rid}/results").status_code == 401
    assert put(scoring, key=key).json() == receipt
    assert put(scoring).status_code == 409
    assert act(owner, rid, "reopen", reason="补评", duration_seconds=120).status_code == 200
    assert put(scoring, judge=1, body=payload("80")).status_code == 200
    assert put(scoring, body=payload("100", 1)).status_code == 200
    assert act(owner, rid, "close").status_code == 200
    results = history(owner, rid)
    assert results[0] == first and len(results) == 2
    assert results[1]["calculation"]["final_score"] == "90.00"
    assert sorted(b["revision"] for b in results[1]["calculation"]["ballots"]) == [1, 2]
    assert owner.get(f"/api/v1/events/{event_id}/ranking").json() == []
    assert act(owner, rid, "no-result", reason="拒绝隐藏有效成绩").status_code == 409
    assert act(owner, rid, "publish").status_code == 200
    assert act(owner, rid, "reopen", reason="已公布", duration_seconds=None).status_code == 409
    assert put(scoring, body=payload("70", 2)).status_code == 409
    assert history(owner, rid) == results
    assert owner.get(f"/api/v1/events/{event_id}/ranking").json()[0]["final_score"] == "90.00"
    unfinished = event_action(owner, event_id, "finish")
    assert unfinished.json()["error"]["code"] == "UNFINISHED_ROUNDS"
    assert scoring[0]["rounds"][1]["id"] in unfinished.json()["error"]["message"]
    assert event_action(owner, event_id, "archive").status_code == 409
    assert control(owner, scoring[0]["rounds"][1], "skip", reason="弃权").status_code == 200
    assert event_action(owner, event_id, "finish").status_code == 200
    assert event_action(owner, event_id, "archive").status_code == 200
    assert put(scoring, key=key).json() == receipt
    assert history(owner, rid) == results


def test_no_result_pause_close_and_active_reopen(scoring, clients):
    owner = clients[0]
    rid = scoring[0]["rounds"][0]["id"]
    assert act(owner, rid, "pause").status_code == 200
    assert act(owner, rid, "close", reason="全部缺席").status_code == 200
    assert control(owner, scoring[0]["rounds"][1], "open").status_code == 200
    assert (
        act(owner, rid, "reopen", reason="补评", duration_seconds=60).json()["error"]["code"]
        == "ACTIVE_ROUND_EXISTS"
    )
    assert act(owner, rid, "no-result", reason="无法补评").status_code == 200
    assert act(owner, rid, "reopen", reason="终态", duration_seconds=None).status_code == 409
    assert act(owner, rid, "publish").status_code == 409


def test_close_races_submit_and_original_receipt(scoring, clients):
    owner = clients[0]
    rid = scoring[0]["rounds"][0]["id"]
    gate = Barrier(2)
    key = str(uuid4())

    def submit():
        gate.wait()
        return put(scoring, key=key)

    def close():
        gate.wait()
        return act(owner, rid, "close", reason="现场收评")

    with ThreadPoolExecutor(2) as pool:
        a, b = pool.submit(submit), pool.submit(close)
        saved, closed = a.result(), b.result()
    assert closed.status_code == 200
    calculation = history(owner, rid)[0]["calculation"]
    assert calculation["valid_count"] == (1 if saved.status_code == 200 else 0)
    assert saved.status_code in {200, 409}
    if saved.status_code == 200:
        scoring[1][0].app.state.clock = lambda: scoring[2] + timedelta(minutes=2)
        assert put(scoring, key=key).json() == saved.json()
        assert calculation["ballots"][0]["receipt_id"] == saved.json()["receipt_id"]


@pytest.mark.parametrize("model", [ResultSnapshot, EventAudit, OutboxEvent])
def test_close_failure_rolls_back_everything(scoring, clients, event_db, model):
    owner = clients[0]
    rid = scoring[0]["rounds"][0]["id"]
    before = owner.get(f"/api/v1/rounds/{rid}").json()

    def fail(*_):
        raise RuntimeError("injected failure")

    sa_event.listen(model, "before_insert", fail)
    try:
        assert act(owner, rid, "close", reason="未收齐").status_code == 500
    finally:
        sa_event.remove(model, "before_insert", fail)
    assert owner.get(f"/api/v1/rounds/{rid}").json() == before
    assert history(owner, rid) == []
    with event_db[0].transaction() as session:
        assert (
            session.scalar(
                select(OutboxEvent).where(
                    OutboxEvent.event_id == scoring[0]["event"]["id"],
                    OutboxEvent.type == "round.closed",
                )
            )
            is None
        )


@pytest.mark.parametrize(
    "algorithm,count,score",
    [("mean", 4, "90.00"), ("trimmed_mean", 4, None), ("trimmed_mean", 5, "90.00")],
)
def test_five_judges_threshold_and_recomputation(clients, mobiles, algorithm, count, score):
    owner = clients[0]
    event = owner.post(
        "/api/v1/events",
        json={
            "title": "门槛验收",
            "scoring_rule": {
                "criteria": [{"criterion_id": "total", "name": "总分"}],
                "algorithm": algorithm,
                "minimum_ballots": 4 if algorithm == "mean" else 5,
            },
        },
    ).json()
    base = f"/api/v1/events/{event['id']}"
    owner.post(base + "/entries", json={"number": "1", "name": "项目"})
    for i in range(5):
        owner.post(base + "/judges", json={"number": f"00{i}", "name": f"评委{i}"})
    published = owner.post(base + "/publish").json()
    rid = published["rounds"][0]["id"]
    assert act(owner, rid, "open").status_code == 200
    mobile = mobiles[0]
    for credential in published["generated_credentials"][:count]:
        csrf = mobile.get("/api/v1/judge-sessions/csrf").json()["csrf_token"]
        mobile.headers["X-CSRF-Token"] = csrf
        verified = mobile.post(
            "/api/v1/judge-sessions/verify",
            json={"public_code": published["event"]["public_code"], "code": credential["code"]},
        ).json()
        exchanged = mobile.post(
            "/api/v1/judge-sessions/exchange",
            json={"confirmation_token": verified["confirmation_token"]},
        ).json()
        mobile.headers["X-CSRF-Token"] = exchanged["csrf_token"]
        assert (
            mobile.put(
                f"/api/v1/rounds/{rid}/my-ballot",
                json=payload(),
                headers={"Idempotency-Key": str(uuid4())},
            ).status_code
            == 200
        )
        assert mobile.post("/api/v1/judge-sessions/logout").status_code == 204
    assert act(owner, rid, "close", reason="到场人员已交").status_code == 200
    calculation = history(owner, rid)[0]["calculation"]
    assert calculation["final_score"] == score
    assert calculation["valid_count"] == count and calculation["expected_count"] == 5
    rule = scoring_rule({**event["scoring_rule"], "expected_count": 5})
    recomputed = aggregate(
        rule,
        [
            Ballot(b["judge_number"], {s["criterion_id"]: s["value"] for s in b["scores"]})
            for b in calculation["ballots"]
        ],
    )
    assert (str(recomputed.final_score) if recomputed.can_publish else None) == score
    assert act(owner, rid, "publish").status_code == (200 if score else 409)
    if algorithm == "trimmed_mean" and count == 5:
        assert {
            b["judge_number"]: b["exclusion"] for b in calculation["ballots"] if b["exclusion"]
        } == {"000": "lowest", "004": "highest"}
