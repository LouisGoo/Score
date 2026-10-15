"""租约领取 -> 事务外发布 -> 条件确认，崩溃后至少一次重投。"""

import json
import logging
from datetime import timedelta
from uuid import uuid4

from redis.exceptions import RedisError
from sqlalchemy import or_, select, update

from score_api.db import utc_now
from score_api.outbox.models import OutboxEvent
from score_api.realtime.broker import CHANNEL
from score_api.worker import Batch

logger = logging.getLogger("score.outbox")


def envelope(row):
    # 18 以前的内部事件没有冻结的角色版本，不能用当前版本伪造历史序列。
    legacy = row.payload.get("protocol") != 1
    action = row.type
    if action == "ballot.submitted":
        action = "progress.updated"
    return {
        "event_id": row.event_id,
        "message_id": row.id,
        "type": "stream.resync" if legacy else action,
        "server_time": row.created_at.isoformat(),
        "streams": [] if legacy else row.payload["streams"],
    }


class OutboxWorker:
    def __init__(self, database, redis, *, batch_size=50, clock=utc_now):
        self.database, self.redis, self.batch_size, self.clock = database, redis, batch_size, clock

    def claim(self):
        now, token = self.clock(), uuid4().hex
        with self.database.transaction() as session:
            row = session.scalar(
                select(OutboxEvent)
                .where(
                    OutboxEvent.delivered_at.is_(None),
                    or_(OutboxEvent.available_at.is_(None), OutboxEvent.available_at <= now),
                )
                .order_by(OutboxEvent.available_at, OutboxEvent.created_at, OutboxEvent.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if row is None:
                return None
            row.claim_token = token
            row.available_at = now + timedelta(seconds=30)
            row.retry_count += 1
            return row.id, token, row.retry_count, envelope(row)

    def finish(self, id_, token, *, delivered, attempts):
        now = self.clock()
        with self.database.transaction() as session:
            session.execute(
                update(OutboxEvent)
                .where(
                    OutboxEvent.id == id_,
                    OutboxEvent.claim_token == token,
                    OutboxEvent.delivered_at.is_(None),
                )
                .values(
                    delivered_at=now if delivered else None,
                    claim_token=None,
                    available_at=None
                    if delivered
                    else now + timedelta(seconds=min(60, 2 ** min(attempts, 6))),
                )
            )

    def run_once(self):
        scanned = delivered = failed = 0
        for _ in range(self.batch_size):
            claim = self.claim()
            if claim is None:
                break
            id_, token, attempts, message = claim
            scanned += 1
            try:
                # 此时没有数据库事务/连接；Redis 返回 0 订阅者仍属于正常发布。
                self.redis.publish(CHANNEL, json.dumps(message))
            except (RedisError, OSError) as error:
                logger.error("outbox_publish_failed", extra={"error_type": type(error).__name__})
                self.finish(id_, token, delivered=False, attempts=attempts)
                failed += 1
                # Redis 故障不遍历整个 backlog，退避由主循环执行。
                break
            self.finish(id_, token, delivered=True, attempts=attempts)
            delivered += 1
        return Batch(scanned, delivered, failed)
