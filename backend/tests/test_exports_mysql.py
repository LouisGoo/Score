import csv
import io
from urllib.parse import unquote
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_ballots_mysql import payload, put
from test_ballots_mysql import scoring as scoring
from test_results_mysql import act, event_action, history
from test_rounds_mysql import control

from score_api.events.models import EventAudit
from score_api.exports import service

pytestmark = pytest.mark.mysql


def export(owner, event_id, kind="summary", include=False):
    response = owner.get(
        f"/api/v1/events/{event_id}/exports/{kind}",
        params={"include_unpublished": str(include).lower()},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert "成绩" in unquote(response.headers["content-disposition"]) or kind != "summary"
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))


def test_filters_history_missing_frozen_scores_and_archive(scoring, clients):
    owner = clients[0]
    eid = scoring[0]["event"]["id"]
    rid = scoring[0]["rounds"][0]["id"]
    receipt = put(scoring, body=payload("0")).json()
    assert export(owner, eid) == []
    assert export(owner, eid, "details") == []
    assert act(owner, rid, "close", reason="缺席").status_code == 200
    rows = export(owner, eid, include=True)
    closed = next(r for r in rows if r["任务ID"] == rid)
    assert closed["公布状态"] == "未公布"
    assert closed["有效份数"] == "1" and closed["应交份数"] == "2"
    assert closed["最终分"] == "" and closed["名次"] == ""
    details = [r for r in export(owner, eid, "details", True) if r["任务ID"] == rid]
    assert {r["计入标记"] for r in details} == {"计入", "缺交（收评时）"}
    assert next(r for r in details if r["回执ID"] == receipt["receipt_id"])["原始分"] == "0"
    assert act(owner, rid, "reopen", reason="补评", duration_seconds=None).status_code == 200
    revised = put(scoring, body=payload("100", 1)).json()
    assert put(scoring, judge=1, body=payload("80")).status_code == 200
    interim = [r for r in export(owner, eid, "details", True) if r["任务ID"] == rid]
    assert all(r["快照状态"] == "历史收评（已重开）" for r in interim)
    old = next(r for r in interim if r["回执ID"] == receipt["receipt_id"])
    assert old["当前有效版本"] == "2" and old["快照采用版本"] == "1"
    assert old["个人总分"] == "0"
    assert act(owner, rid, "close").status_code == 200
    assert act(owner, rid, "publish").status_code == 200
    rows = export(owner, eid)
    assert len(rows) == 1 and rows[0]["最终分"] == "90.00" and rows[0]["名次"] == "1"
    frozen = history(owner, rid)[-1]
    page = owner.get(f"/api/v1/events/{eid}/snapshot").json()
    assert rows[0]["结果快照ID"] == frozen["id"]
    assert (
        rows[0]["最终分"]
        == frozen["calculation"]["final_score"]
        == page["ranking"][0]["final_score"]
    )
    details = export(owner, eid, "details")
    assert len(details) == 3
    assert (
        next(r for r in details if r["回执ID"] == receipt["receipt_id"])["计入标记"]
        == "非快照采用版本"
    )
    assert next(r for r in details if r["回执ID"] == revised["receipt_id"])["快照采用版本"] == "2"
    assert all(r["公布状态"] == "已公布" and r["规则版本"] == "1" for r in details)
    assert control(owner, scoring[0]["rounds"][1], "skip", reason="弃权").status_code == 200
    assert event_action(owner, eid, "finish").status_code == 200
    assert event_action(owner, eid, "archive").status_code == 200
    assert export(owner, eid)[0]["最终分"] == "90.00"


@pytest.mark.parametrize("kind", ["summary", "details", "audit"])
def test_owner_role_session_and_input_boundaries(scoring, clients, kind):
    owner, other = clients
    eid = scoring[0]["event"]["id"]
    url = f"/api/v1/events/{eid}/exports/{kind}"
    assert other.get(url).status_code == 404
    assert scoring[1][0].get(url).status_code == 401
    assert owner.get(f"/api/v1/events/{uuid4().hex}/exports/{kind}").status_code == 404
    assert owner.get(url + "?include_unpublished=bad").status_code == 422
    assert owner.get(f"/api/v1/events/{eid}/exports/wrong").status_code == 422
    draft = owner.post("/api/v1/events", json={"title": "草稿"}).json()
    assert owner.get(f"/api/v1/events/{draft['id']}/exports/{kind}").status_code == 409
    assert owner.post("/api/v1/auth/logout").status_code == 204
    assert owner.get(url).status_code == 401


def test_audit_scope_redaction_and_formula_protection(scoring, clients, event_db):
    owner, other = clients
    eid = scoring[0]["event"]["id"]
    rid = scoring[0]["rounds"][0]["id"]
    assert put(scoring).status_code == 200
    assert put(scoring, body=payload("80", 1)).status_code == 200
    assert act(owner, rid, "pause").status_code == 200
    assert act(owner, rid, "close", reason="=危险公式").status_code == 200
    assert act(owner, rid, "reopen", reason="补评", duration_seconds=None).status_code == 200
    judge_id = scoring[0]["generated_credentials"][0]["judge_id"]
    reset = owner.post(
        f"/api/v1/events/{eid}/judges/{judge_id}/reset-credential", json={"reason": "遗失"}
    )
    assert reset.status_code == 200, reset.text
    other.post("/api/v1/events", json={"title": "其他活动机密"})
    with event_db[0].transaction() as session:
        audit = session.scalar(
            select(EventAudit).where(
                EventAudit.event_id == eid, EventAudit.action == "credential.reset"
            )
        )
        audit.after = {
            **audit.after,
            "token": "DO-NOT-EXPORT",
            "credential_hash": "DO-NOT-EXPORT",
            "nested": {"code": "DO-NOT-EXPORT"},
        }
    default = export(owner, eid, "audit")
    assert all(not r["任务ID"] for r in default)
    rows = export(owner, eid, "audit", True)
    actions = {r["操作"] for r in rows}
    assert {
        "round.open",
        "round.pause",
        "round.closed",
        "round.reopened",
        "ballot.revised",
        "credential.reset",
    } <= actions
    close = next(r for r in rows if r["操作"] == "round.closed")
    assert close["原因"] == "'=危险公式" and close["公布状态"] == "未公布"
    text = str(rows)
    assert "DO-NOT-EXPORT" not in text and "其他活动机密" not in text
    for credential in scoring[0]["generated_credentials"] + [reset.json()]:
        assert credential["code"] not in text
    assert "credential_hash" not in text and "credential_lookup" not in text


def test_export_uses_single_read_view_during_publication(scoring, clients, monkeypatch):
    owner = clients[0]
    eid = scoring[0]["event"]["id"]
    rid = scoring[0]["rounds"][0]["id"]
    assert put(scoring).status_code == 200
    assert put(scoring, judge=1).status_code == 200
    assert act(owner, rid, "close").status_code == 200
    original = service.public_data

    def publish_between_reads(session, event):
        assert act(owner, rid, "publish").status_code == 200
        return original(session, event)

    monkeypatch.setattr(service, "public_data", publish_between_reads)
    rows = export(owner, eid, include=True)
    row = next(r for r in rows if r["任务ID"] == rid)
    assert row["结果状态"] == "CLOSED" and row["名次"] == ""
    monkeypatch.setattr(service, "public_data", original)
    assert export(owner, eid)[0]["名次"] == "1"


def test_weighted_trimmed_export_and_user_text(clients, mobiles):
    owner = clients[0]
    created = owner.post(
        "/api/v1/events",
        json={
            "title": '=中文,"活动"',
            "scoring_rule": {
                "mode": "multi",
                "algorithm": "trimmed_mean",
                "minimum_ballots": 5,
                "criteria": [
                    {"criterion_id": "a", "name": "能力", "maximum": "10", "weight": "0.3"},
                    {"criterion_id": "b", "name": "@表现", "maximum": "100", "weight": "0.7"},
                ],
            },
        },
    )
    assert created.status_code == 201, created.text
    eid = created.json()["id"]
    base = f"/api/v1/events/{eid}"
    owner.post(base + "/entries", json={"number": "001", "name": "+对象\n甲"})
    for i in range(5):
        owner.post(base + "/judges", json={"number": f"00{i}", "name": f"评委{i}"})
    published = owner.post(base + "/publish").json()
    rid = published["rounds"][0]["id"]
    assert act(owner, rid, "open").status_code == 200
    mobile = mobiles[0]
    for credential in published["generated_credentials"]:
        mobile.headers["X-CSRF-Token"] = mobile.get("/api/v1/judge-sessions/csrf").json()[
            "csrf_token"
        ]
        verified = mobile.post(
            "/api/v1/judge-sessions/verify",
            json={
                "public_code": published["event"]["public_code"],
                "code": credential["code"],
            },
        ).json()
        exchanged = mobile.post(
            "/api/v1/judge-sessions/exchange",
            json={
                "confirmation_token": verified["confirmation_token"],
            },
        ).json()
        mobile.headers["X-CSRF-Token"] = exchanged["csrf_token"]
        response = mobile.put(
            f"/api/v1/rounds/{rid}/my-ballot",
            json={
                "rule_version": 1,
                "expected_ballot_revision": 0,
                "scores": [
                    {"criterion_id": "a", "value": "9.1"},
                    {"criterion_id": "b", "value": "87.3"},
                ],
            },
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 200, response.text
        assert mobile.post("/api/v1/judge-sessions/logout").status_code == 204
    assert act(owner, rid, "close").status_code == 200
    assert act(owner, rid, "publish").status_code == 200
    rows = export(owner, eid, "details")
    assert len(rows) == 10
    assert {r["个人总分"] for r in rows} == {"88.41"}
    assert {r["最终分"] for r in rows} == {"88.41"}
    assert {r["对象编号"] for r in rows} == {"001"}
    assert {r["对象名称"] for r in rows} == {"'+对象\n甲"}
    assert {r["活动"] for r in rows} == {'\'=中文,"活动"'}
    assert {r["维度名称"] for r in rows} == {"能力", "'@表现"}
    frozen = history(owner, rid)[-1]["calculation"]
    for ballot in frozen["ballots"]:
        detail = [r for r in rows if r["回执ID"] == ballot["receipt_id"]]
        assert len(detail) == 2
        assert all(r["剔除原因"] == (ballot["exclusion"] or "") for r in detail)
    assert sum(r["计入标记"] == "剔除" for r in rows) == 4
