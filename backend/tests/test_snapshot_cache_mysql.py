import pytest
from sqlalchemy import event as sa_event
from test_ballots_mysql import payload, put
from test_ballots_mysql import scoring as scoring
from test_snapshots_mysql import grant, screen, snap

pytestmark = pytest.mark.mysql


def test_cached_snapshots_check_authority_versions_and_identity(scoring, clients):
    owner, other = clients
    first, second = scoring[1]
    event_id = scoring[0]["event"]["id"]
    credential = grant(owner, event_id)
    assert put(scoring, body=payload("73.1")).status_code == 200
    first_data = snap(first, event_id, "judge")
    assert first_data["my_ballots"] and not snap(second, event_id, "judge")["my_ballots"]
    assert screen(other, credential).status_code == 200
    # 同身份版本不变时重用数据；每次授权与版本仍从数据库读取。
    statements = []
    engine = first.app.state.database.engine

    def capture(_conn, _cursor, sql, *_):
        statements.append(sql)

    sa_event.listen(engine, "before_cursor_execute", capture)
    try:
        assert snap(first, event_id, "judge") == first_data
        assert not any("score_ballot_revisions" in sql for sql in statements)
        statements.clear()
        revision = first.get(
            "/api/v1/realtime/version", params={"role": "judge", "event_id": event_id}
        )
        assert revision.status_code == 200
        assert revision.json()["version"] == first_data["version"]
        assert len(statements) <= 4
    finally:
        sa_event.remove(engine, "before_cursor_execute", capture)
    assert put(scoring, body=payload("74.2", 1)).status_code == 200
    assert snap(first, event_id, "judge")["version"] == first_data["version"] + 1
    assert snap(second, event_id, "judge")["version"] == first_data["version"]
    assert (
        owner.delete(f"/api/v1/events/{event_id}/screen-grants/{credential['id']}").status_code
        == 204
    )
    assert screen(other, credential).status_code == 401
    assert first.post("/api/v1/judge-sessions/logout").status_code == 204
    assert first.get(f"/api/v1/judge/events/{event_id}/snapshot").status_code == 401
    assert (
        first.get(
            "/api/v1/realtime/version", params={"role": "judge", "event_id": event_id}
        ).status_code
        == 401
    )


def test_version_read_does_not_require_redis_and_uses_same_scope(scoring, clients):
    owner, other = clients
    event_id = scoring[0]["event"]["id"]
    credential = grant(owner, event_id)
    for client, role, extra, expected in (
        (owner, "admin", {}, snap(owner, event_id)["version"]),
        (scoring[1][0], "judge", {}, snap(scoring[1][0], event_id, "judge")["version"]),
        (
            other,
            "screen",
            {"grant_id": credential["id"]},
            screen(other, credential).json()["version"],
        ),
    ):
        result = client.get(
            "/api/v1/realtime/version",
            params={"event_id": event_id, "role": role, **extra},
            headers={"Authorization": "Bearer " + credential["token"]},
        )
        assert result.status_code == 200
        assert result.json()["version"] == expected
        assert result.headers["cache-control"] == "no-store"
    denied = other.get("/api/v1/realtime/version", params={"event_id": event_id, "role": "admin"})
    assert denied.status_code == 401


def test_public_cache_is_shared_across_grants_but_revocation_is_never_cached(scoring, clients):
    owner = clients[0]
    event_id = scoring[0]["event"]["id"]
    first, second = grant(owner, event_id), grant(owner, event_id)
    assert screen(owner, first).status_code == 200
    statements = []
    engine = owner.app.state.database.engine

    def capture(_conn, _cursor, sql, *_):
        statements.append(sql)

    sa_event.listen(engine, "before_cursor_execute", capture)
    try:
        assert screen(owner, second).status_code == 200
        assert not any("score_result_snapshots" in sql for sql in statements)
    finally:
        sa_event.remove(engine, "before_cursor_execute", capture)
    assert owner.delete(f"/api/v1/events/{event_id}/screen-grants/{first['id']}").status_code == 204
    assert screen(owner, first).status_code == 401
    assert screen(owner, second).status_code == 200
