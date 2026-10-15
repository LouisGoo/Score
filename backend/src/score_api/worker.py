"""独立的到期收评进程；仅使用 worker 的 2 条连接预算。"""

import argparse
import logging
import random
import signal
from dataclasses import dataclass
from threading import Event as StopEvent
from uuid import uuid4

from sqlalchemy import select, tuple_
from sqlalchemy.exc import SQLAlchemyError

from score_api.core.config import Settings
from score_api.core.logging import configure_logging
from score_api.db import Database, utc_now
from score_api.events.models import Event
from score_api.results.service import freeze_result
from score_api.rounds.models import ScoringRound

logger = logging.getLogger("score.worker")


def close_due(database, event_id, round_id, clock=utc_now):
    with database.transaction() as session:
        # 扫描不锁任务；先活动后任务。跳过繁忙活动，下一轮重新发现。
        event = session.scalar(
            select(Event).where(Event.id == event_id).with_for_update(skip_locked=True)
        )
        if event is None or event.status not in {"READY", "RUNNING"}:
            return False
        row = session.scalar(
            select(ScoringRound)
            .where(
                ScoringRound.id == round_id,
                ScoringRound.event_id == event_id,
            )
            .with_for_update(skip_locked=True)
        )
        now = clock()
        if row is None or row.status != "OPEN" or row.deadline_at is None or row.deadline_at > now:
            return False
        freeze_result(
            session, event, row, None, "评分时间已到", uuid4().hex, now, source="deadline"
        )
    return True


@dataclass(frozen=True)
class Batch:
    scanned: int
    closed: int
    failed: int


class DeadlineWorker:
    def __init__(self, database, *, batch_size=50, clock=utc_now):
        if type(batch_size) is not int or not 1 <= batch_size <= 500:
            raise ValueError("batch_size must be in 1..500")
        self.database = database
        self.batch_size = batch_size
        self.clock = clock
        self.cursor = None

    def run_once(self):
        with self.database.transaction() as session:
            query = select(ScoringRound.event_id, ScoringRound.id, ScoringRound.deadline_at).where(
                ScoringRound.status == "OPEN",
                ScoringRound.deadline_at <= self.clock(),
            )
            if self.cursor is not None:
                query = query.where(tuple_(ScoringRound.deadline_at, ScoringRound.id) > self.cursor)
            rows = list(
                session.execute(
                    query.order_by(ScoringRound.deadline_at, ScoringRound.id).limit(self.batch_size)
                )
            )
        # 有界 keyset 翻页，单个失败任务不饿死后面的任务；扫描至末尾后回到最早任务。
        self.cursor = (rows[-1].deadline_at, rows[-1].id) if rows else None
        closed = failed = 0
        for row in rows:
            try:
                closed += close_due(self.database, row.event_id, row.id, self.clock)
            except Exception as error:
                # 不输出 SQL、连接 URL 或评分内容；保留失败任务，由下一轮重试。
                failed += 1
                logger.error("close_failed round_id=%s error_type=%s", row.id, type(error).__name__)
        return Batch(len(rows), closed, failed)


def run_loop(worker, stop, *, minimum=0.5, maximum=15.0, jitter=random.uniform):
    delay = minimum
    while not stop.is_set():
        try:
            batch = worker.run_once()
            busy = batch.scanned > 0 and batch.closed > 0 and batch.failed == 0
            if batch.closed:
                logger.info("deadline_closed count=%s", batch.closed)
        except SQLAlchemyError as error:
            logger.error("scan_failed error_type=%s", type(error).__name__)
            busy = False
        delay = minimum if busy else min(maximum, delay * 2)
        # Event.wait 支持 SIGTERM/SIGINT 立即退出；空闲/失败指数退避，避免查询风暴。
        stop.wait(jitter(delay * 0.8, delay))


def main():
    parser = argparse.ArgumentParser(description="关闭到期评分任务；不自动运行数据库迁移")
    parser.add_argument("--once", action="store_true", help="处理一批后退出，用于运行检查")
    parser.add_argument(
        "--batch-size", type=int, default=50, choices=range(1, 501), metavar="1..500"
    )
    args = parser.parse_args()
    configure_logging()
    database = redis = None
    try:
        settings = Settings()
        database = Database(settings, role="worker")
        if not database.is_ready():
            logger.error("database_not_ready")
            return 1
        worker = DeadlineWorker(database, batch_size=args.batch_size)
        if settings.redis_url is not None:
            from redis import Redis

            from score_api.outbox.worker import OutboxWorker

            redis = Redis.from_url(
                settings.redis_url.get_secret_value(), socket_connect_timeout=2, socket_timeout=2
            )
            worker = CombinedWorker(
                worker, OutboxWorker(database, redis, batch_size=args.batch_size)
            )
        if args.once:
            result = worker.run_once()
            logger.info(
                "scan_complete scanned=%s closed=%s failed=%s",
                result.scanned,
                result.closed,
                result.failed,
            )
            return 1 if result.failed else 0
        stop = StopEvent()
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *_: stop.set())
        run_loop(worker, stop)
        return 0
    except (SQLAlchemyError, ValueError) as error:
        logger.error("worker_unavailable error_type=%s", type(error).__name__)
        return 1
    finally:
        if redis is not None:
            redis.close()
        if database is not None:
            database.dispose()


class CombinedWorker:
    def __init__(self, deadline, outbox):
        self.deadline, self.outbox = deadline, outbox

    def run_once(self):
        deadline = self.deadline.run_once()
        outbox = self.outbox.run_once()
        return Batch(
            deadline.scanned + outbox.scanned,
            deadline.closed + outbox.closed,
            deadline.failed + outbox.failed,
        )


if __name__ == "__main__":
    raise SystemExit(main())
