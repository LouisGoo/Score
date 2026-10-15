"""Restore drill requires an explicitly configured local independent MySQL server."""

import os
import shutil
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool
from test_ballots_mysql import payload, put
from test_ballots_mysql import scoring as scoring
from test_exports_mysql import export
from test_results_mysql import act, history

from score_api import ops
from score_api.events.models import EventSnapshot
from score_api.main import create_app
from score_api.results.service import scoring_rule
from score_api.scoring import Ballot, aggregate

pytestmark = pytest.mark.mysql


@pytest.fixture
def restore_target():
    raw = os.environ.get("SCORE_TEST_RESTORE_SERVER_URL")
    if not raw:
        pytest.skip("independent local restore server not configured")
    url = make_url(raw)
    if url.host not in {"127.0.0.1", "localhost"} or url.database != "mysql":
        pytest.fail("restore drill requires local administrative mysql database")
    name = "score_ops24_" + uuid4().hex + "_restore"
    engine = create_engine(url, poolclass=NullPool)
    with engine.connect() as connection:
        connection.execute(text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4"))
    try:
        yield url.set(database=name)
    finally:
        # Only the randomly named database created above is ever dropped.
        with engine.connect() as connection:
            connection.execute(text(f"DROP DATABASE `{name}`"))
        engine.dispose()


def test_independent_restore_preserves_scores_receipts_and_results(
    scoring,
    clients,
    mysql_settings,
    restore_target,
    tmp_path,
):
    dump_bin = os.environ.get("SCORE_TEST_MYSQLDUMP", "mysqldump")
    mysql_bin = os.environ.get("SCORE_TEST_MYSQL", "mysql")
    if not shutil.which(dump_bin) or not shutil.which(mysql_bin):
        pytest.skip("MySQL 8 client tools required")
    owner = clients[0]
    eid = scoring[0]["event"]["id"]
    rid = scoring[0]["rounds"][0]["id"]
    key = str(uuid4())
    original = put(scoring, body=payload("0"), key=key)
    assert original.status_code == 200
    receipt = original.json()
    assert put(scoring, body=payload("100", 1)).status_code == 200
    assert put(scoring, judge=1, body=payload("80")).status_code == 200
    assert act(owner, rid, "close").status_code == 200
    assert act(owner, rid, "publish").status_code == 200
    expected_results = history(owner, rid)
    assert expected_results[-1]["calculation"]["final_score"] == "90.00"
    expected_exports = {kind: export(owner, eid, kind) for kind in ("summary", "details", "audit")}
    source = make_url(mysql_settings.database_url.get_secret_value())
    assert (source.host, source.port) != (restore_target.host, restore_target.port)
    before = ops.fingerprint(source)
    failed = tmp_path / "failed.sql.gz"
    with pytest.raises(FileNotFoundError):
        ops.backup(source, failed, str(tmp_path / "missing-mysqldump"))
    assert not failed.exists()
    assert not (tmp_path / "failed.sql.gz.partial").exists()
    archive = tmp_path / "drill.sql.gz"
    assert ops.backup(source, archive, dump_bin)["status"] == "backup_complete"
    assert archive.stat().st_mode & 0o777 == 0o600
    assert ops.restore(restore_target, archive, restore_target.database, mysql_bin)
    after = ops.fingerprint(restore_target)
    assert before == after
    for table in (
        "score_ballot_revisions",
        "score_ballot_idempotency",
        "score_result_snapshots",
        "score_event_snapshots",
        "score_outbox",
    ):
        assert after[table]["rows"] > 0
    # Re-running restore must not overwrite the existing data.
    with pytest.raises(ValueError, match="empty"):
        ops.restore(restore_target, archive, restore_target.database, mysql_bin)
    assert ops.fingerprint(restore_target) == after

    settings = owner.app.state.settings.model_copy(
        update={
            "database_url": SecretStr(restore_target.render_as_string(hide_password=False)),
        }
    )
    with TestClient(create_app(settings), base_url="https://score.test") as restored_owner:
        restored_owner.app.state.clock = lambda: scoring[2]
        restored_owner.cookies.update(owner.cookies)
        restored_owner.headers.update(owner.headers)
        assert restored_owner.get("/api/v1/health/ready").status_code == 200
        restored_results = history(restored_owner, rid)
        assert restored_results == expected_results
        with restored_owner.app.state.database.transaction() as session:
            frozen = session.scalar(select(EventSnapshot).where(EventSnapshot.event_id == eid))
            rule = scoring_rule(frozen.scoring_rule)
        calculation = restored_results[-1]["calculation"]
        recomputed = aggregate(
            rule,
            [
                Ballot(b["judge_number"], {v["criterion_id"]: v["value"] for v in b["scores"]})
                for b in calculation["ballots"]
            ],
        )
        assert str(recomputed.final_score) == calculation["final_score"] == "90.00"
        for kind, rows in expected_exports.items():
            assert export(restored_owner, eid, kind) == rows
    with TestClient(create_app(settings), base_url="https://score.test") as mobile:
        mobile.cookies.update(scoring[1][0].cookies)
        mobile.headers.update(scoring[1][0].headers)
        replay = mobile.put(
            f"/api/v1/rounds/{rid}/my-ballot",
            json=payload("0"),
            headers={"Idempotency-Key": key},
        )
        assert replay.status_code == 200
        assert replay.json() == receipt
    assert ops.storage(source, 1, 2)["estimated_bytes"] > 0
