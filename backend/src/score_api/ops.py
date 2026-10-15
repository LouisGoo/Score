"""Explicit maintenance commands; never read the application's .env implicitly."""

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

from score_api.core.config import Settings
from score_api.db import create_db_engine

NAME = re.compile(r"^[a-zA-Z0-9_]+$")
TABLE = re.compile(r"^score_[a-z0-9_]+$")
SOURCE_ENV = "SCORE_BACKUP_DATABASE_URL"
TARGET_ENV = "SCORE_RESTORE_DATABASE_URL"


def url_from_env(name):
    raw = os.environ.get(name)
    if not raw:
        raise ValueError("missing connection environment")
    url = make_url(raw)
    if url.drivername != "mysql+pymysql" or not NAME.fullmatch(url.database or ""):
        raise ValueError("invalid MySQL database")
    return url


def engine_for(url):
    return create_db_engine(
        Settings(
            _env_file=None,
            environment="development",
            DATABASE_URL=url.render_as_string(hide_password=False),
        ),
        role="migration",
    )


def tables_for(connection):
    rows = connection.execute(
        text(
            "SELECT TABLE_NAME, ENGINE, TABLE_TYPE FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND LEFT(TABLE_NAME, 6) = 'score_' "
            "ORDER BY TABLE_NAME"
        )
    ).all()
    if not rows or "score_alembic_version" not in {r[0] for r in rows}:
        raise ValueError("project schema not found")
    if any(not TABLE.fullmatch(r[0]) or r[1] != "InnoDB" or r[2] != "BASE TABLE" for r in rows):
        raise ValueError("only InnoDB project tables are supported")
    triggers = connection.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.TRIGGERS "
            "WHERE TRIGGER_SCHEMA = DATABASE() AND LEFT(EVENT_OBJECT_TABLE, 6) = 'score_'"
        )
    ).scalar_one()
    if triggers:
        raise ValueError("custom triggers require a separate backup procedure")
    return [r[0] for r in rows]


def option_quote(value):
    return (
        '"'
        + str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        + '"'
    )


@contextmanager
def client_options(url):
    options = {
        "host": url.host or "localhost",
        "port": url.port or 3306,
        "user": url.username or "",
        "password": url.password or "",
        "protocol": "TCP",
        "default-character-set": "utf8mb4",
    }
    query = dict(url.query)
    allowed = {"ssl_ca", "ssl_cert", "ssl_key", "ssl_verify_cert", "ssl_verify_identity", "charset"}
    if set(query) - allowed:
        raise ValueError("unsupported connection options")
    for key in ("ssl_ca", "ssl_cert", "ssl_key"):
        if key in query:
            options[key.replace("_", "-")] = query[key]

    def truth(key):
        return str(query.get(key, "")).lower() in {"1", "true", "yes"}

    if truth("ssl_verify_identity"):
        options["ssl-mode"] = "VERIFY_IDENTITY"
    elif truth("ssl_verify_cert"):
        options["ssl-mode"] = "VERIFY_CA"
    elif "ssl_ca" in query:
        raise ValueError("CA requires explicit certificate verification")
    with tempfile.TemporaryDirectory(prefix="score-client-") as directory:
        path = Path(directory) / "client.cnf"
        with path.open("x", encoding="utf-8") as output:
            os.chmod(path, 0o600)
            output.write("[client]\n")
            for key, value in options.items():
                output.write(f"{key}={option_quote(value)}\n")
        yield str(path)


def child_env():
    return {
        k: v
        for k, v in os.environ.items()
        if k not in {SOURCE_ENV, TARGET_ENV, "DATABASE_URL", "MYSQL_PWD"}
    }


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def backup(url, destination, dump_bin="mysqldump"):
    destination = Path(destination)
    manifest = Path(str(destination) + ".json")
    partial = Path(str(destination) + ".partial")
    if any(p.exists() for p in (destination, manifest, partial)):
        raise ValueError("backup destination already exists")
    engine = engine_for(url)
    try:
        with engine.connect() as connection:
            tables = tables_for(connection)
    finally:
        engine.dispose()
    owns_partial = False
    # No DDL during the snapshot. mysqldump provides one transaction for all tables.
    try:
        with client_options(url) as options, tempfile.TemporaryFile() as errors:
            with partial.open("xb") as raw:
                owns_partial = True
                os.chmod(partial, 0o600)
                command = [
                    dump_bin,
                    f"--defaults-file={options}",
                    "--single-transaction",
                    "--skip-lock-tables",
                    "--no-tablespaces",
                    "--set-gtid-purged=OFF",
                    "--column-statistics=0",
                    "--hex-blob",
                    "--skip-add-drop-table",
                    "--skip-add-locks",
                    "--skip-disable-keys",
                    "--skip-triggers",
                    url.database,
                    *tables,
                ]
                with subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=errors,
                    env={**child_env(), "MYSQL_TEST_LOGIN_FILE": options + ".unused"},
                ) as process:
                    with gzip.GzipFile(fileobj=raw, mode="wb") as compressed:
                        shutil.copyfileobj(process.stdout, compressed)
                    if process.wait() != 0:
                        raise RuntimeError("mysqldump failed")
                raw.flush()
                os.fsync(raw.fileno())
        os.link(partial, destination)
        partial.unlink()
        data = {
            "format": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_database": url.database,
            "tables": tables,
            "sha256": sha256(destination),
        }
        with manifest.open("x", encoding="utf-8") as output:
            os.chmod(manifest, 0o600)
            json.dump(data, output, ensure_ascii=False, indent=2)
        return {"status": "backup_complete", "tables": len(tables), "sha256": data["sha256"]}
    finally:
        if owns_partial and partial.exists():
            partial.unlink()


def validate_restore(url, confirmation, manifest, archive):
    if not url.database.endswith("_restore") or confirmation != url.database:
        raise ValueError("target must end in _restore and be explicitly confirmed")
    if manifest.get("format") != 1 or manifest.get("source_database") == url.database:
        raise ValueError("not an independent restore target")
    tables = manifest.get("tables")
    if (
        not isinstance(tables, list)
        or not tables
        or any(not isinstance(t, str) or not TABLE.fullmatch(t) for t in tables)
    ):
        raise ValueError("invalid backup manifest")
    if sha256(archive) != manifest.get("sha256"):
        raise ValueError("backup checksum mismatch")
    # Validate gzip trailer before executing any SQL.
    with gzip.open(archive, "rb") as source:
        for _ in iter(lambda: source.read(1024 * 1024), b""):
            pass


def restore(url, archive, confirmation, mysql_bin="mysql"):
    archive = Path(archive)
    manifest = json.loads(Path(str(archive) + ".json").read_text(encoding="utf-8"))
    validate_restore(url, confirmation, manifest, archive)
    engine = engine_for(url)
    try:
        with engine.connect() as connection:
            count = connection.execute(
                text("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()")
            ).scalar_one()
            if count:
                raise ValueError("restore target must be empty")
        with client_options(url) as options, tempfile.TemporaryFile() as errors:
            with subprocess.Popen(
                [
                    mysql_bin,
                    f"--defaults-file={options}",
                    "--binary-mode",
                    f"--database={url.database}",
                ],
                stdin=subprocess.PIPE,
                stdout=errors,
                stderr=errors,
                env={**child_env(), "MYSQL_TEST_LOGIN_FILE": options + ".unused"},
            ) as process:
                try:
                    with gzip.open(archive, "rb") as source:
                        shutil.copyfileobj(source, process.stdin)
                finally:
                    process.stdin.close()
                if process.wait() != 0:
                    raise RuntimeError("restore failed; target may be partially populated")
        with engine.connect() as connection:
            if tables_for(connection) != manifest["tables"]:
                raise RuntimeError("restored table set differs")
        return {"status": "restored_verify_before_use", "tables": len(manifest["tables"])}
    finally:
        engine.dispose()


def fingerprint(url):
    engine = engine_for(url)
    result = {}
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            with connection.begin():
                for table in tables_for(connection):
                    keys = inspect(connection).get_pk_constraint(table)["constrained_columns"]
                    if not keys:
                        raise ValueError("fingerprint requires primary keys")
                    order = ", ".join(f"`{key}`" for key in keys)
                    digest, count = hashlib.sha256(), 0
                    rows = connection.execution_options(stream_results=True).execute(
                        text(f"SELECT * FROM `{table}` ORDER BY {order}")
                    )
                    for row in rows:
                        encoded = json.dumps(
                            list(row), default=str, ensure_ascii=False, separators=(",", ":")
                        ).encode()
                        digest.update(len(encoded).to_bytes(8, "big"))
                        digest.update(encoded)
                        count += 1
                    rows.close()
                    result[table] = {"rows": count, "sha256": digest.hexdigest()}
        return result
    finally:
        engine.dispose()


def storage_level(size, warning_mb=350, critical_mb=425):
    if not 0 < warning_mb < critical_mb:
        raise ValueError("thresholds must satisfy 0 < warning < critical")
    return (
        "critical"
        if size >= critical_mb * 1_000_000
        else ("warning" if size >= warning_mb * 1_000_000 else "ok")
    )


def storage(url, warning_mb=350, critical_mb=425):
    storage_level(0, warning_mb, critical_mb)
    engine = engine_for(url)
    try:
        with engine.connect() as connection:
            size = int(
                connection.execute(
                    text(
                        "SELECT COALESCE(SUM(DATA_LENGTH + INDEX_LENGTH), 0) "
                        "FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()"
                    )
                ).scalar_one()
            )
        return {
            "status": storage_level(size, warning_mb, critical_mb),
            "estimated_bytes": size,
            "estimated_mb": round(size / 1_000_000, 2),
            "warning_mb": warning_mb,
            "critical_mb": critical_mb,
        }
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("backup")
    command.add_argument("archive")
    command.add_argument("--mysqldump", default="mysqldump")
    command = commands.add_parser("restore")
    command.add_argument("archive")
    command.add_argument("--confirm-target", required=True)
    command.add_argument("--mysql", default="mysql")
    command = commands.add_parser("fingerprint")
    command.add_argument("--target", action="store_true")
    command = commands.add_parser("storage")
    command.add_argument("--warning-mb", type=int, default=350)
    command.add_argument("--critical-mb", type=int, default=425)
    args = parser.parse_args()
    try:
        target = args.command == "restore" or (args.command == "fingerprint" and args.target)
        url = url_from_env(TARGET_ENV if target else SOURCE_ENV)
        if args.command == "backup":
            result = backup(url, args.archive, args.mysqldump)
        elif args.command == "restore":
            result = restore(url, args.archive, args.confirm_target, args.mysql)
        elif args.command == "fingerprint":
            result = fingerprint(url)
        else:
            result = storage(url, args.warning_mb, args.critical_mb)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return {"warning": 10, "critical": 20}.get(result.get("status"), 0)
    except Exception as error:
        # Client stderr / SQL / URLs may contain credentials; never echo them.
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
