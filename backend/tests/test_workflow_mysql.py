"""AT-01: real HTTP handlers + MySQL, with five isolated judge cookie jars.

Only administrator provisioning uses SQL. All activity operations use public APIs.
This is an API workflow test, not a browser or physical-device test.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event as sa_event
from test_ballots_mysql import payload
from test_exports_mysql import export
from test_results_mysql import act, event_action, history
from test_snapshots_mysql import grant, screen, snap

from score_api.auth.models import Admin
from score_api.core.security import hash_password
from score_api.main import create_app
from score_api.outbox.models import OutboxEvent

pytestmark = pytest.mark.mysql
ORIGIN = "https://score.test"


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json() if status != 204 else None


def join(mobile, published, credential):
    csrf = ok(mobile.get("/api/v1/judge-sessions/csrf"))["csrf_token"]
    mobile.headers.update({"Origin": ORIGIN, "X-CSRF-Token": csrf})
    verified = ok(
        mobile.post(
            "/api/v1/judge-sessions/verify",
            json={"public_code": published["event"]["public_code"], "code": credential["code"]},
        )
    )
    identity = ok(
        mobile.post(
            "/api/v1/judge-sessions/exchange",
            json={"confirmation_token": verified["confirmation_token"]},
        )
    )
    mobile.headers["X-CSRF-Token"] = identity["csrf_token"]


def submit(mobile, rid, value="90", revision=0, key=None):
    return mobile.put(
        f"/api/v1/rounds/{rid}/my-ballot",
        json=payload(value, revision),
        headers={"Idempotency-Key": key or str(uuid4())},
    )


@pytest.fixture
def workflow(clients, event_db):
    owner, other = clients
    password = "workflow-test-only-password"
    with event_db[0].transaction() as session:
        session.get(Admin, event_db[1][0]).password_hash = hash_password(password)
    # Exercise actual login, rather than retaining the fixture's injected session.
    ok(owner.post("/api/v1/auth/logout"), 204)
    owner.cookies.clear()
    owner.headers["X-CSRF-Token"] = ok(owner.get("/api/v1/auth/csrf"))["csrf_token"]
    logged_in = ok(
        owner.post("/api/v1/auth/login", json={"login": event_db[1][0], "password": password})
    )
    owner.headers["X-CSRF-Token"] = logged_in["csrf_token"]
    with ExitStack() as stack:
        # Independent app instances also prevent accidental reliance on process-local state.
        devices = [
            stack.enter_context(
                TestClient(create_app(owner.app.state.settings.model_copy()), base_url=ORIGIN)
            )
            for _ in range(6)
        ]
        yield owner, other, devices[:5], devices[5]
        for device in devices:
            assert device.app.state.database.engine.pool.checkedout() == 0


def publish(owner, algorithm="trimmed_mean"):
    event = ok(
        owner.post(
            "/api/v1/events",
            json={
                "title": "五评委三对象闭环",
                "duration_seconds": None,
                "scoring_rule": {
                    "algorithm": algorithm,
                    "minimum_ballots": 5 if algorithm == "trimmed_mean" else 4,
                    "criteria": [{"criterion_id": "total", "name": "总分"}],
                },
            },
        ),
        201,
    )
    base = f"/api/v1/events/{event['id']}"
    for i in range(3):
        ok(owner.post(base + "/entries", json={"number": f"00{i}", "name": f"对象{i}"}), 201)
    for i in range(5):
        ok(owner.post(base + "/judges", json={"number": f"00{i}", "name": f"评委{i}"}), 201)
    return ok(owner.post(base + "/publish"))


@pytest.mark.parametrize("algorithm", ["trimmed_mean", "mean"])
def test_five_judges_three_entries_create_to_archive(workflow, algorithm):
    owner, other, mobiles, display = workflow
    published = publish(owner, algorithm)
    eid = published["event"]["id"]
    base = f"/api/v1/events/{eid}"
    credentials = published["generated_credentials"]
    access = grant(owner, eid)
    assert ok(display.get("/api/v1/join/" + published["event"]["public_code"]))
    assert display.get(f"/api/v1/judge/events/{eid}/snapshot").status_code == 401
    assert other.get(base + "/snapshot").status_code == 404
    for mobile, credential in zip(mobiles, credentials, strict=True):
        join(mobile, published, credential)
        assert snap(mobile, eid, "judge")["identity"]["id"] == credential["judge_id"]

    frozen = []
    first_key = str(uuid4())
    first_receipt = None
    for index, row in enumerate(published["rounds"]):
        rid = row["id"]
        ok(act(owner, rid, "open"))
        public = ok(screen(display, access))
        assert public["current_round"]["id"] == rid
        assert public["current_round"]["submitted_count"] == 0
        assert public["current_round"]["expected_count"] == 5
        assert len(public["ranking"]) == index
        for mobile in mobiles:
            assert (
                next(r for r in snap(mobile, eid, "judge")["rounds"] if r["id"] == rid)["status"]
                == "OPEN"
            )
        if index == 0:
            blocked = event_action(owner, eid, "finish")
            assert blocked.json()["error"]["code"] == "UNFINISHED_ROUNDS"
            assert rid in blocked.json()["error"]["message"]
            ok(act(owner, rid, "pause"))
            assert submit(mobiles[0], rid).status_code == 409
            assert ok(screen(display, access))["display"]["mode"] == "paused"
            ok(act(owner, rid, "resume"))
        else:
            # A stale draft cannot be redirected into the new active object.
            assert submit(mobiles[0], published["rounds"][index - 1]["id"]).status_code == 409

        values = ["80", "85", "90", "95", "100"] if index == 0 else ["80"] * 5
        receipts = []
        for j, (mobile, value) in enumerate(zip(mobiles, values, strict=True)):
            key = first_key if index == j == 0 else str(uuid4())
            receipt = ok(submit(mobile, rid, value, key=key))
            assert ok(submit(mobile, rid, value, key=key)) == receipt
            receipts.append(receipt)
            if index == j == 0:
                first_receipt = receipt
            # Four ballots: trimmed mean must demand a fifth; mean K=4 may publish.
            if index == 1 and j == 3:
                assert act(owner, rid, "close").json()["error"]["code"] == "CLOSE_REASON_REQUIRED"
                ok(act(owner, rid, "close", reason="一位暂未交，核对门槛"))
                partial = history(owner, rid)[-1]["calculation"]
                assert partial["valid_count"] == 4 and partial["expected_count"] == 5
                assert partial["final_score"] == (None if algorithm == "trimmed_mean" else "80.00")
                if algorithm == "trimmed_mean":
                    assert (
                        act(owner, rid, "publish").json()["error"]["code"] == "INSUFFICIENT_BALLOTS"
                    )
                ok(act(owner, rid, "reopen", reason="第五位补评", duration_seconds=None))

        if index == 0:
            revised = ok(submit(mobiles[0], rid, "81", revision=1))
            assert revised["revision"] == 2
            assert submit(mobiles[0], rid, "82", revision=1).status_code == 409
            ok(submit(mobiles[0], rid, "80", revision=2))
        assert ok(screen(display, access))["current_round"]["submitted_count"] == 5
        for mobile, receipt in zip(mobiles, receipts, strict=True):
            personal = snap(mobile, eid, "judge")
            assert receipt["receipt_id"] in str(personal["my_ballots"])
            assert all(
                r["receipt_id"] not in str(personal)
                for r in receipts
                if r["receipt_id"] != receipt["receipt_id"]
            )
        ok(act(owner, rid, "close"))
        result = history(owner, rid)[-1]
        expected = "90.00" if index == 0 else "80.00"
        assert result["calculation"]["final_score"] == expected
        assert len(result["calculation"]["ballots"]) == 5
        if algorithm == "trimmed_mean":
            assert sum(bool(b["exclusion"]) for b in result["calculation"]["ballots"]) == 2
        public = ok(screen(display, access))
        assert len(public["published_results"]) == index
        assert all(r["receipt_id"] not in str(public) for r in receipts)
        assert len(export(owner, eid)) == index
        ok(act(owner, rid, "publish"))
        assert ok(screen(display, access))["published_results"][-1]["final_score"] == expected
        assert submit(mobiles[0], rid, "70", revision=3).status_code == 409
        assert act(owner, rid, "reopen", reason="已公布", duration_seconds=None).status_code == 409
        frozen.append(history(owner, rid))

    ranking = snap(owner, eid)["ranking"]
    assert [r["rank"] for r in ranking] == [1, 2, 2]
    assert ranking == ok(screen(display, access))["ranking"]
    assert all(snap(m, eid, "judge")["ranking"] == ranking for m in mobiles)
    ok(event_action(owner, eid, "finish"))
    ok(event_action(owner, eid, "archive"))
    assert ok(screen(display, access))["event"]["status"] == "ARCHIVED"
    assert ok(screen(display, access))["display"]["mode"] == "ended"
    assert (
        ok(submit(mobiles[0], published["rounds"][0]["id"], "80", key=first_key)) == first_receipt
    )
    for row, results in zip(published["rounds"], frozen, strict=True):
        assert history(owner, row["id"]) == results
    summary, details, audit = [export(owner, eid, kind) for kind in ("summary", "details", "audit")]
    assert [r["最终分"] for r in summary] == ["90.00", "80.00", "80.00"]
    assert len(details) == 17  # Fifteen initial scores plus two immutable revisions.
    assert {r["规则版本"] for r in details} == {"1"}
    assert {r["结果快照ID"] for r in summary} == {h[-1]["id"] for h in frozen}
    assert {"event.finished", "event.archived", "ballot.revised"} <= {r["操作"] for r in audit}
    assert all(c["code"] not in str(audit) for c in credentials)
    ok(owner.delete(base + f"/screen-grants/{access['id']}"), 204)
    assert screen(display, access).status_code == 401
    ok(owner.post("/api/v1/auth/logout"), 204)
    assert owner.get(base + "/exports/summary").status_code == 401


def test_concurrent_five_judges_failed_commit_and_retry(workflow):
    owner, _, mobiles, display = workflow
    published = publish(owner)
    eid = published["event"]["id"]
    rid = published["rounds"][0]["id"]
    for mobile, credential in zip(mobiles, published["generated_credentials"], strict=True):
        join(mobile, published, credential)
    access = grant(owner, eid)
    ok(act(owner, rid, "open"))
    key = str(uuid4())

    def fail(*_):
        raise RuntimeError("workflow injected outbox failure")

    sa_event.listen(OutboxEvent, "before_insert", fail)
    try:
        assert submit(mobiles[0], rid, "80", key=key).status_code == 500
    finally:
        sa_event.remove(OutboxEvent, "before_insert", fail)
    assert snap(mobiles[0], eid, "judge")["my_ballots"] == []
    assert ok(screen(display, access))["current_round"]["submitted_count"] == 0
    gate = Barrier(5)
    keys = [key] + [str(uuid4()) for _ in range(4)]

    def send(index):
        gate.wait(timeout=10)
        return ok(submit(mobiles[index], rid, str(80 + 5 * index), key=keys[index]))

    with ThreadPoolExecutor(5) as pool:
        receipts = list(pool.map(send, range(5)))
    assert len({r["receipt_id"] for r in receipts}) == 5
    assert ok(screen(display, access))["current_round"]["submitted_count"] == 5
    ok(act(owner, rid, "close"))
    result = history(owner, rid)[-1]["calculation"]
    assert result["valid_count"] == 5 and result["final_score"] == "90.00"
    assert {b["receipt_id"] for b in result["ballots"]} == {r["receipt_id"] for r in receipts}
    # Lost responses are recovered after close without adding versions or headcount.
    for index, receipt in enumerate(receipts):
        assert ok(submit(mobiles[index], rid, str(80 + 5 * index), key=keys[index])) == receipt
    assert len(snap(owner, eid)["ballots"]) == 5


def test_two_closed_entries_concurrently_reopen_only_one(workflow):
    owner, _, _, second_console = workflow
    published = publish(owner)
    eid = published["event"]["id"]
    targets = published["rounds"][:2]
    for row in targets:
        ok(act(owner, row["id"], "open"))
        ok(act(owner, row["id"], "close", reason="等待补评"))
    second_console.cookies.update(owner.cookies)
    second_console.headers.update(owner.headers)
    gate = Barrier(2)

    def reopen(client, rid):
        current = ok(client.get(f"/api/v1/rounds/{rid}"))
        gate.wait(timeout=10)
        return client.post(
            f"/api/v1/rounds/{rid}/reopen",
            json={
                "expected_version": current["version"],
                "reason": "并发补评",
                "duration_seconds": None,
            },
        )

    with ThreadPoolExecutor(2) as pool:
        jobs = [
            pool.submit(reopen, client, row["id"])
            for client, row in zip((owner, second_console), targets, strict=True)
        ]
        responses = [job.result(timeout=15) for job in jobs]
    assert sorted(r.status_code for r in responses) == [200, 409]
    rejected = next(r for r in responses if r.status_code == 409)
    assert rejected.json()["error"]["code"] == "ACTIVE_ROUND_EXISTS"
    states = [r["status"] for r in snap(owner, eid)["rounds"]]
    assert states.count("OPEN") == 1 and states.count("CLOSED") == 1
    for row in targets:
        assert len(history(owner, row["id"])) == 1
