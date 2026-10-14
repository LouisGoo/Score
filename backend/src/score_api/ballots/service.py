"""锁内校验与全事务有限重试；只有提交成功才返回持久化回执。"""

import hashlib
import json
import random
import time
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from score_api.ballots.models import Ballot, BallotAudit, BallotRevision, IdempotencyRecord
from score_api.ballots.schemas import BallotReceipt
from score_api.core.errors import APIError
from score_api.core.streams import advance_views
from score_api.events.models import EventSnapshot
from score_api.judge_sessions.service import lock_principal
from score_api.outbox.service import record
from score_api.rounds.models import RoundJudge
from score_api.rounds.service import require_before_deadline, round_in_event
from score_api.scoring import Criterion, ScoringError, ScoringRule, personal_total


def canonical_request(round_id, body):
    scores = sorted(
        (
            {"criterion_id": s.criterion_id, "value": format(Decimal(s.value).normalize(), "f")}
            for s in body.scores
        ),
        key=lambda s: (s["criterion_id"], s["value"]),
    )
    content = {**body.model_dump(), "round_id": round_id, "scores": scores}
    digest = hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return scores, digest


def authorized_round(session, principal, round_id, clock):
    # 与重置/退出共同持有活动锁，再锁任务；不反向加锁。
    event, judge, auth = lock_principal(session, principal, clock)
    row = round_in_event(session, event.id, round_id, write=True)
    now = clock()
    # 任务锁等待期间会话也可能自然到期。
    if auth.expires_at <= now:
        raise APIError(401, "SESSION_EXPIRED", "会话已失效，请重新验证身份")
    if session.get(RoundJudge, (row.id, judge.id)) is None:
        raise APIError(403, "FORBIDDEN", "不属于本任务应交名单")
    return event, row, now


def make_receipt(ballot, revision):
    return BallotReceipt(
        ballot_id=ballot.id,
        receipt_id=revision.id,
        round_id=ballot.round_id,
        revision=revision.revision,
        rule_version=revision.rule_version,
        scores=revision.scores,
        total_score=format(revision.display_total, ".2f"),
        accepted_at=revision.accepted_at,
    )


def read_ballot(database, principal, round_id, key, clock):
    with database.transaction() as session:
        authorized_round(session, principal, round_id, clock)
        if key is not None:
            saved = session.get(IdempotencyRecord, (principal.judge_id, key))
            if saved is None or saved.response["round_id"] != round_id:
                raise APIError(404, "RECEIPT_NOT_FOUND", "本次操作尚无成功回执")
            return BallotReceipt.model_validate(saved.response)
        ballot = session.scalar(
            select(Ballot).where(Ballot.round_id == round_id, Ballot.judge_id == principal.judge_id)
        )
        if ballot is None:
            raise APIError(404, "BALLOT_NOT_FOUND", "尚未提交评分")
        revision = session.scalar(
            select(BallotRevision).where(
                BallotRevision.ballot_id == ballot.id,
                BallotRevision.revision == ballot.current_revision,
            )
        )
        return make_receipt(ballot, revision)


def submit_once(database, principal, round_id, body, key, scores, digest, request_id, clock):
    with database.transaction() as session:
        event, row, now = authorized_round(session, principal, round_id, clock)
        saved = session.get(IdempotencyRecord, (principal.judge_id, key))
        if saved is not None:
            if saved.request_hash != digest:
                raise APIError(409, "IDEMPOTENCY_CONFLICT", "同一幂等键已用于不同请求")
            return BallotReceipt.model_validate(saved.response)
        if event.status not in {"READY", "RUNNING"}:
            raise APIError(409, "EVENT_NOT_RUNNING", "活动当前只读")
        if row.status != "OPEN":
            raise APIError(409, "ROUND_NOT_OPEN", "评分任务尚未开放或已关闭")
        require_before_deadline(row, now)
        snapshot = session.get(EventSnapshot, row.rule_id)
        if body.rule_version != snapshot.rule_version:
            raise APIError(409, "RULE_VERSION_MISMATCH", "评分规则版本已变化")
        rule_data = snapshot.scoring_rule
        rule = ScoringRule(
            criteria=tuple(
                Criterion(c["criterion_id"], c["maximum"], c["weight"], c["step"])
                for c in rule_data["criteria"]
            ),
            expected_count=rule_data["expected_count"],
            algorithm=rule_data["algorithm"],
            minimum_ballots=rule_data["minimum_ballots"],
        )
        if len({s["criterion_id"] for s in scores}) != len(scores):
            raise APIError(422, "SCORE_INVALID", "评分维度不能重复")
        try:
            total = personal_total(rule, {s["criterion_id"]: s["value"] for s in scores})
        except ScoringError:
            raise APIError(422, "SCORE_INVALID", "评分维度、范围或步长不合法") from None
        ballot = session.scalar(
            select(Ballot).where(Ballot.round_id == row.id, Ballot.judge_id == principal.judge_id)
        )
        previous = ballot.current_revision if ballot else 0
        if previous != body.expected_ballot_revision:
            raise APIError(409, "REVISION_CONFLICT", "评分版本已变化，请核验本人最新评分")
        if previous and not snapshot.allow_revisions:
            raise APIError(409, "REVISIONS_DISABLED", "此活动不允许改分")
        if ballot is None:
            ballot = Ballot(
                id=uuid4().hex,
                event_id=event.id,
                round_id=row.id,
                judge_id=principal.judge_id,
                current_revision=1,
            )
            session.add(ballot)
        else:
            ballot.current_revision += 1
        session.flush()
        revision = BallotRevision(
            id=uuid4().hex,
            event_id=event.id,
            ballot_id=ballot.id,
            revision=ballot.current_revision,
            rule_version=body.rule_version,
            scores=scores,
            computed_total=total,
            # 展示分从高精度计算直接舍入，避免 DECIMAL 缓存造成二次舍入。
            display_total=total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            accepted_at=now,
        )
        session.add(revision)
        result = make_receipt(ballot, revision)
        session.add(
            IdempotencyRecord(
                judge_id=principal.judge_id,
                key=key,
                event_id=event.id,
                ballot_id=ballot.id,
                request_hash=digest,
                response=result.model_dump(mode="json"),
                created_at=now,
            )
        )
        action = "ballot.revised" if previous else "ballot.submitted"
        session.add(
            BallotAudit(
                id=uuid4().hex,
                event_id=event.id,
                ballot_id=ballot.id,
                judge_id=principal.judge_id,
                action=action,
                before_revision=previous or None,
                after_revision=ballot.current_revision,
                request_id=request_id,
                created_at=now,
            )
        )
        event.version += 1
        event.updated_at = now
        advance_views(session, event, judge_id=principal.judge_id, public=not previous)
        record(session, event, action, now, public=not previous, judge_id=principal.judge_id)
    return result


def submit_ballot(database, principal, round_id, body, key, request_id, clock):
    scores, digest = canonical_request(round_id, body)
    for attempt in range(3):
        try:
            return submit_once(
                database, principal, round_id, body, key, scores, digest, request_id, clock
            )
        except OperationalError as error:
            # 仅死锁/锁等待超时重试；离开事务上下文已整笔回滚。
            if not error.orig.args or error.orig.args[0] not in {1205, 1213}:
                raise
            if attempt == 2:
                raise APIError(
                    503, "SERVICE_UNAVAILABLE", "评分服务繁忙，请按原幂等键核验", retry_after=3
                ) from None
            time.sleep(random.uniform(0.01, 0.03) * (attempt + 1))
