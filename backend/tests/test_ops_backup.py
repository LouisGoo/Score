import gzip
import json
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from score_api import ops


@pytest.mark.parametrize(
    "size,expected",
    [
        (0, "ok"),
        (349_999_999, "ok"),
        (350_000_000, "warning"),
        (424_999_999, "warning"),
        (425_000_000, "critical"),
    ],
)
def test_storage_thresholds(size, expected):
    assert ops.storage_level(size) == expected


def test_custom_thresholds_and_invalid_order():
    assert ops.storage_level(2_000_000, 1, 2) == "critical"
    with pytest.raises(ValueError):
        ops.storage_level(0, 425, 350)


def test_option_file_protects_and_escapes_password():
    url = make_url("mysql+pymysql://user@localhost/score").set(password='a"b\\c\nd')
    with ops.client_options(url) as filename:
        path = Path(filename)
        assert path.stat().st_mode & 0o777 == 0o600
        assert 'password="a\\"b\\\\c\\nd"' in path.read_text()
    assert not path.exists()


def test_tls_verification_not_silently_disabled():
    url = make_url("mysql+pymysql://u@db/score?ssl_ca=/ca.pem&ssl_verify_identity=true")
    with ops.client_options(url) as path:
        assert 'ssl-mode="VERIFY_IDENTITY"' in Path(path).read_text()
    with (
        pytest.raises(ValueError),
        ops.client_options(make_url("mysql+pymysql://u@db/score?ssl_ca=/ca.pem")),
    ):
        pass


def test_restore_guards_and_corruption(tmp_path):
    path = tmp_path / "backup.sql.gz"
    with gzip.open(path, "wb") as output:
        output.write(b"test")
    manifest = {
        "format": 1,
        "source_database": "score",
        "tables": ["score_alembic_version"],
        "sha256": ops.sha256(path),
    }
    target = make_url("mysql+pymysql://root@localhost/check_restore")
    ops.validate_restore(target, "check_restore", manifest, path)
    for url, confirmation in [
        (target, "wrong"),
        (target.set(database="score"), "score"),
        (target.set(database="score_restore"), "score_restore"),
    ]:
        altered = {**manifest, "source_database": "score_restore"}
        with pytest.raises(ValueError):
            ops.validate_restore(url, confirmation, altered, path)
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        ops.validate_restore(target, "check_restore", manifest, path)


def test_cli_does_not_echo_credentials(monkeypatch, capsys):
    monkeypatch.setenv(ops.SOURCE_ENV, "SECRET_INVALID_URL")
    monkeypatch.setattr("sys.argv", ["ops", "storage"])
    assert ops.main() == 1
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "failed"
    assert "SECRET" not in output


def test_child_process_does_not_inherit_connection_secrets(monkeypatch):
    for name in (ops.SOURCE_ENV, ops.TARGET_ENV, "DATABASE_URL", "MYSQL_PWD"):
        monkeypatch.setenv(name, "secret")
        assert name not in ops.child_env()


def test_backup_refuses_existing_file_before_connecting(tmp_path):
    path = tmp_path / "existing"
    path.write_text("keep")
    with pytest.raises(ValueError, match="already exists"):
        ops.backup(make_url("mysql+pymysql://root@localhost/score"), path)
    assert path.read_text() == "keep"


def test_no_implicit_application_env(monkeypatch):
    monkeypatch.delenv(ops.SOURCE_ENV, raising=False)
    monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://root@localhost/production")
    with pytest.raises(ValueError):
        ops.url_from_env(ops.SOURCE_ENV)


def test_invalid_gzip_rejected_even_with_matching_checksum(tmp_path):
    path = tmp_path / "invalid.sql.gz"
    path.write_bytes(b"not gzip")
    manifest = {
        "format": 1,
        "source_database": "score",
        "tables": ["score_alembic_version"],
        "sha256": ops.sha256(path),
    }
    with pytest.raises(gzip.BadGzipFile):
        ops.validate_restore(
            make_url("mysql+pymysql://root@localhost/check_restore"),
            "check_restore",
            manifest,
            path,
        )
