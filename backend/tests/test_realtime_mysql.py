"""真实 MySQL/Redis + 独立 API 实例验证提交后投递与角色隔离。"""

import json
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import timedelta

import httpx
import pytest
from pydantic import SecretStr
from redis import Redis
from redis.exceptions import ConnectionError
from sqlalchemy import event as sa_event
from starlette.websockets import WebSocketDisconnect
from test_ballots_mysql import payload, put
from test_ballots_mysql import scoring as scoring
from test_results_mysql import act
from test_snapshots_mysql import grant, snap
from websockets.sync.client import connect as socket_connect

from score_api.db import utc_now
from score_api.outbox.models import OutboxEvent
from score_api.outbox.worker import OutboxWorker, envelope
from score_api.realtime.broker import CHANNEL

pytestmark = pytest.mark.mysql


@pytest.fixture(autouse=True)
def realtime_settings(mysql_settings):
    url = os.environ.get("SCORE_TEST_REDIS_URL")
    if not url:
        pytest.skip("需要显式 SCORE_TEST_REDIS_URL")
    redis = Redis.from_url(url)
    redis.ping()
    mysql_settings.redis_url = SecretStr(url)
    mysql_settings.realtime_auth_interval_seconds = 0.2
    yield redis
    redis.close()


def ticket(client, event_id, role="admin", credential=None):
    for _ in range(100):
        if client.app.state.realtime.ready:
            break
        time.sleep(0.01)
    return client.post(
        "/api/v1/realtime/tickets",
        json={
            "event_id": event_id,
            "role": role,
            "grant_id": credential["id"] if credential else None,
        },
        headers={"Authorization": "Bearer " + credential["token"]} if credential else {},
    )


def connect(stack, client, info):
    ws = stack.enter_context(client.websocket_connect(info["stream_path"]))
    ws.send_json({"ticket": info["ticket"]})
    assert ws.receive_json()["type"] == "stream.ready"
    return ws


def notification(ws):
    for _ in range(20):
        message = ws.receive_json()
        if message["type"] != "stream.heartbeat":
            return message
    pytest.fail("没有收到预期通知")


def worker(event_db, redis, clock=utc_now):
    return OutboxWorker(event_db[0], redis, batch_size=100, clock=clock)


def test_roles_versions_and_multiple_api_instances(scoring, clients, event_db, realtime_settings):
    owner, outsider = clients
    first, second = scoring[1]
    event_id, rid = scoring[0]["event"]["id"], scoring[0]["rounds"][0]["id"]
    credential = grant(owner, event_id)
    delivery = worker(event_db, realtime_settings)
    delivery.run_once()
    assert ticket(outsider, event_id).status_code == 401
    assert ticket(first, "f" * 32, "judge").status_code == 404
    with ExitStack() as stack:
        sockets = [
            connect(stack, client, ticket(client, event_id, role, cred).json())
            for client, role, cred in (
                (owner, "admin", None),
                (first, "judge", None),
                (second, "judge", None),
                (outsider, "screen", credential),
            )
        ]
        versions = [
            snap(owner, event_id)["version"],
            snap(first, event_id, "judge")["version"],
            snap(second, event_id, "judge")["version"],
        ]
        receipt = put(scoring, body=payload("73.1")).json()
        delivery.run_once()
        messages = [notification(ws) for ws in sockets]
        assert [m["scope"] for m in messages] == ["admin", "judge", "judge", "screen"]
        assert [m["version"] for m in messages[:3]] == [v + 1 for v in versions]
        assert len({m["message_id"] for m in messages}) == 1
        for m in messages:
            assert m["payload"] == {}
            assert receipt["receipt_id"] not in json.dumps(m)
            assert "73.1" not in json.dumps(m)
        assert put(scoring, body=payload("74.2", 1)).status_code == 200
        delivery.run_once()
        revised = [notification(ws) for ws in sockets[:2]]
        assert [m["version"] for m in revised] == [m["version"] + 1 for m in messages[:2]]
        assert act(owner, rid, "pause").status_code == 200
        delivery.run_once()
        # 他人改分不向第二位评委/大屏发事件，也不占用其流版本。
        for index in (2, 3):
            paused = notification(sockets[index])
            assert paused["type"] == "round.paused"
            assert paused["version"] == messages[index]["version"] + 1


def test_tickets_origin_csrf_event_binding_replay_and_expiry(scoring, clients, realtime_settings):
    owner = clients[0]
    event_id = scoring[0]["event"]["id"]
    assert (
        owner.post(
            "/api/v1/realtime/tickets",
            json={"event_id": event_id, "role": "admin"},
            headers={"X-CSRF-Token": "bad"},
        ).status_code
        == 403
    )
    issued = ticket(owner, event_id).json()
    with (
        pytest.raises(WebSocketDisconnect),
        owner.websocket_connect(issued["stream_path"], headers={"Origin": "https://evil.test"}),
    ):
        pass
    with ExitStack() as stack:
        connect(stack, owner, issued)
        with owner.websocket_connect(issued["stream_path"]) as ws:
            ws.send_json({"ticket": issued["ticket"]})
            with pytest.raises(WebSocketDisconnect) as failure:
                ws.receive_json()
            assert failure.value.code == 4401
    wrong = ticket(owner, event_id).json()
    with owner.websocket_connect("/api/v1/events/" + "f" * 32 + "/stream") as ws:
        ws.send_json({"ticket": wrong["ticket"]})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    expired = ticket(owner, event_id).json()
    from score_api.core.security import token_hash

    realtime_settings.delete("score:ticket:" + token_hash(expired["ticket"]))
    with owner.websocket_connect(expired["stream_path"]) as ws:
        ws.send_json({"ticket": expired["ticket"]})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


@pytest.mark.parametrize("role", ["admin", "judge", "screen"])
def test_revocation_closes_connected_and_outstanding_tickets(
    scoring, clients, event_db, realtime_settings, role
):
    owner = clients[0]
    event_id = scoring[0]["event"]["id"]
    credential = grant(owner, event_id) if role == "screen" else None
    client = scoring[1][0] if role == "judge" else owner
    delivery = worker(event_db, realtime_settings)
    delivery.run_once()
    issued, unused = [ticket(client, event_id, role, credential).json() for _ in range(2)]
    with ExitStack() as stack:
        ws = connect(stack, client, issued)
        if role == "screen":
            response = owner.delete(f"/api/v1/events/{event_id}/screen-grants/{credential['id']}")
        else:
            path = "/auth/logout" if role == "admin" else "/judge-sessions/logout"
            response = client.post("/api/v1" + path)
        assert response.status_code == 204
        delivery.run_once()
        assert notification(ws)["type"] == "session.revoked"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
        with client.websocket_connect(unused["stream_path"]) as late:
            late.send_json({"ticket": unused["ticket"]})
            assert late.receive_json()["type"] == "session.revoked"


def test_crash_recovery_duplicate_delivery_and_concurrent_claims(
    scoring, event_db, realtime_settings
):
    db = event_db[0]
    event_id = scoring[0]["event"]["id"]
    delivery = worker(event_db, realtime_settings)
    delivery.run_once()
    assert put(scoring).status_code == 200
    original = delivery.claim()
    assert original is not None

    # 模拟发布成功、确认前崩溃；租约过期后新进程重投相同 message_id 和角色版本。
    class Publisher:
        def __init__(self):
            self.messages = []

        def publish(self, channel, data):
            assert db.engine.pool.checkedout() == 0
            self.messages.append(json.loads(data))

    sink = Publisher()
    later = worker(event_db, sink, clock=lambda: utc_now() + timedelta(seconds=31))
    assert later.run_once().closed == 1
    assert sink.messages == [original[3]]
    with db.transaction() as session:
        row = session.get(OutboxEvent, original[0])
        assert row.delivered_at is not None and row.retry_count == 2
    assert put(scoring, body=payload("88", 1)).status_code == 200
    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(lambda _: delivery.claim(), range(2)))
    assert sum(c is not None for c in claims) == 1
    claimed = next(c for c in claims if c)

    class Broken:
        def publish(self, *_):
            raise ConnectionError("offline")

    failed = worker(event_db, Broken(), clock=lambda: utc_now() + timedelta(seconds=31))
    assert failed.run_once().failed == 1
    with db.transaction() as session:
        row = session.get(OutboxEvent, claimed[0])
        assert row.delivered_at is None and row.available_at is not None
        assert row.payload["streams"] == claimed[3]["streams"]
        assert row.event_id == event_id


def test_legacy_outbox_requests_resync_without_forging_versions():
    row = OutboxEvent(
        id="x",
        event_id="e",
        version=4,
        type="ballot.submitted",
        payload={"secret": "private"},
        created_at=utc_now(),
    )
    result = envelope(row)
    assert result["type"] == "stream.resync" and result["streams"] == []
    assert "private" not in json.dumps(result)


def test_reset_disconnects_old_judge_and_outbox_failure_rolls_back_round(
    scoring, clients, event_db, realtime_settings
):
    owner, mobile = clients[0], scoring[1][0]
    event_id, rid = scoring[0]["event"]["id"], scoring[0]["rounds"][0]["id"]
    delivery = worker(event_db, realtime_settings)
    delivery.run_once()
    before = snap(owner, event_id)

    def fail(*_):
        raise RuntimeError("outbox unavailable")

    sa_event.listen(OutboxEvent, "before_insert", fail)
    try:
        assert act(owner, rid, "pause").status_code == 500
    finally:
        sa_event.remove(OutboxEvent, "before_insert", fail)
    assert snap(owner, event_id) == before
    with ExitStack() as stack:
        ws = connect(stack, mobile, ticket(mobile, event_id, "judge").json())
        judge_id = snap(mobile, event_id, "judge")["identity"]["id"]
        reset = owner.post(
            f"/api/v1/events/{event_id}/judges/{judge_id}/reset-credential",
            json={"reason": "换机验收"},
        )
        assert reset.status_code == 200, reset.text
        delivery.run_once()
        assert notification(ws)["type"] == "session.revoked"


def test_two_os_api_processes_receive_duplicates_without_cross_event(
    scoring, clients, event_db, realtime_settings, mysql_settings
):
    owner = clients[0]
    event_id = scoring[0]["event"]["id"]
    delivery = worker(event_db, realtime_settings)
    delivery.run_once()
    processes = []
    try:
        with ExitStack() as stack:
            sockets = []
            for _ in range(2):
                with socket.socket() as port_socket:
                    port_socket.bind(("127.0.0.1", 0))
                    port = port_socket.getsockname()[1]
                env = {
                    **os.environ,
                    "DATABASE_URL": mysql_settings.database_url.get_secret_value(),
                    "SCORE_REDIS_URL": mysql_settings.redis_url.get_secret_value(),
                    "SCORE_ALLOWED_ORIGINS": '["https://score.test"]',
                }
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "score_api.main:create_app",
                        "--factory",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--no-access-log",
                    ],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                processes.append(process)
                with httpx.Client() as http:
                    for _ in range(100):
                        try:
                            if (
                                http.get(f"http://127.0.0.1:{port}/api/v1/health/live").status_code
                                == 200
                            ):
                                break
                        except httpx.TransportError:
                            pass
                        time.sleep(0.05)
                    else:
                        pytest.fail("API process did not start")
                issued = ticket(owner, event_id).json()
                ws = stack.enter_context(
                    socket_connect(
                        f"ws://127.0.0.1:{port}" + issued["stream_path"],
                        origin="https://score.test",
                    )
                )
                ws.send(json.dumps({"ticket": issued["ticket"]}))
                assert json.loads(ws.recv(timeout=5))["type"] == "stream.ready"
                sockets.append(ws)
            assert put(scoring).status_code == 200
            claimed = delivery.claim()
            message = claimed[3]
            for item in ({**message, "event_id": "f" * 32}, message, message):
                realtime_settings.publish(CHANNEL, json.dumps(item))
            for ws in sockets:
                received = [json.loads(ws.recv(timeout=5)) for _ in range(2)]
                assert received[0] == received[1]
                assert received[0]["event_id"] == event_id
                assert received[0]["message_id"] == message["message_id"]
                assert received[0]["payload"] == {}
    finally:
        for process in processes:
            process.terminate()
            process.wait(timeout=10)
