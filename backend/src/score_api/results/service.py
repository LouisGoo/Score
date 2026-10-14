from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from score_api.ballots.models import Ballot, BallotRevision
from score_api.core.errors import APIError
from score_api.core.streams import advance_views, automatic_screen
from score_api.events.models import Entry, EventSnapshot
from score_api.events.schemas import EventInfo
from score_api.events.service import audit, owned_event
from score_api.outbox.service import record
from score_api.results.models import ResultSnapshot
from score_api.results.schemas import Calculation, RankingInfo, ResultInfo
from score_api.rounds.models import RoundJudge, ScoringRound
from score_api.rounds.service import owned_round, state
from score_api.scoring import Ballot as ScoreBallot
from score_api.scoring import Criterion, RankingEntry, ScoringRule, aggregate, rank_results


def scoring_rule(data):
    return ScoringRule(
        criteria=tuple(
            Criterion(c["criterion_id"], c["maximum"], c["weight"], c["step"])
            for c in data["criteria"]
        ),
        expected_count=data["expected_count"],
        algorithm=data["algorithm"],
        minimum_ballots=data["minimum_ballots"],
    )


def latest_result(session, round_id):
    return session.scalar(
        select(ResultSnapshot)
        .where(ResultSnapshot.round_id == round_id)
        .order_by(ResultSnapshot.round_version.desc())
        .limit(1)
    )


def record_change(session, event, row, actor_id, action, before, reason, request_id, now):
    event.version += 1
    event.updated_at = now
    automatic_screen(event, action, row)
    advance_views(session, event)
    if row is not None:
        row.version += 1
    target = row or event
    after = {"status": target.status, "version": target.version, "reason": reason}
    audit(session, event, actor_id, action, target.id, before, after, request_id, now)
    record(session, event, action, now, public=True)


def freeze_result(session, event, row, actor_id, reason, request_id, now, *, source="manual"):
    """调用方必须先锁活动再锁任务；与提交使用相同的串行边界。"""
    snapshot = session.get(EventSnapshot, row.rule_id)
    expected = set(
        session.scalars(select(RoundJudge.event_judge_id).where(RoundJudge.round_id == row.id))
    )
    numbers = {j["id"]: j["number"] for j in snapshot.judges}
    versions = list(
        session.execute(
            select(Ballot, BallotRevision)
            .join(
                BallotRevision,
                (BallotRevision.ballot_id == Ballot.id)
                & (BallotRevision.revision == Ballot.current_revision),
            )
            .where(Ballot.round_id == row.id)
            .order_by(Ballot.judge_id)
        )
    )
    if len(versions) < len(expected) and not reason:
        raise APIError(422, "CLOSE_REASON_REQUIRED", "未收齐评分，收评必须填写原因")
    computed = aggregate(
        scoring_rule(snapshot.scoring_rule),
        [
            ScoreBallot(numbers[b.judge_id], {s["criterion_id"]: s["value"] for s in r.scores})
            for b, r in versions
        ],
    )
    calculation = Calculation(
        rule_version=snapshot.rule_version,
        algorithm=snapshot.scoring_rule["algorithm"],
        valid_count=computed.valid_count,
        expected_count=computed.expected_count,
        minimum_ballots=computed.minimum_ballots,
        final_score=format(computed.final_score, ".2f") if computed.can_publish else None,
        missing_judge_ids=sorted(expected - {b.judge_id for b, _ in versions}),
        ballots=[
            dict(
                judge_id=b.judge_id,
                judge_number=numbers[b.judge_id],
                ballot_id=b.id,
                receipt_id=r.id,
                revision=r.revision,
                scores=r.scores,
                total=str(c.total),
                exclusion=c.exclusion,
            )
            for (b, r), c in zip(versions, computed.ballots, strict=True)
        ],
    )
    before = {"status": row.status, "version": row.version}
    row.status = "CLOSED"
    row.deadline_at = None
    row.remaining_seconds = None
    record_change(session, event, row, actor_id, "round.closed", before, reason, request_id, now)
    result = ResultSnapshot(
        id=uuid4().hex,
        event_id=event.id,
        round_id=row.id,
        round_version=row.version,
        rule_id=row.rule_id,
        calculation=calculation.model_dump(mode="json"),
        reason=reason,
        source=source,
        closed_at=now,
    )
    session.add(result)
    session.flush()
    return result


def control(database, owner_id, round_id, action, body, request_id, clock):
    with database.transaction() as session:
        event, row = owned_round(session, owner_id, round_id, write=True)
        now = clock()
        if event.status not in {"READY", "RUNNING"}:
            raise APIError(409, "EVENT_NOT_RUNNING", "活动当前只读")
        if row.version != body.expected_version:
            raise APIError(409, "VERSION_CONFLICT", "任务版本已变化，请刷新后确认")
        allowed = {"OPEN", "PAUSED"} if action == "close" else {"CLOSED"}
        if row.status not in allowed:
            raise APIError(409, "ROUND_STATE_CONFLICT", "任务状态不允许此操作")
        reason = getattr(body, "reason", None)
        if action == "close":
            freeze_result(session, event, row, owner_id, reason, request_id, now)
        else:
            before = {"status": row.status, "version": row.version}
            if action == "reopen":
                active = session.scalar(
                    select(ScoringRound.id).where(
                        ScoringRound.event_id == event.id,
                        ScoringRound.status.in_(("OPEN", "PAUSED")),
                    )
                )
                if active:
                    raise APIError(409, "ACTIVE_ROUND_EXISTS", "活动已有开放或暂停的评分任务")
                row.status = "OPEN"
                row.deadline_at = (
                    now + timedelta(seconds=body.duration_seconds)
                    if body.duration_seconds is not None
                    else None
                )
                event.status = "RUNNING"
            else:
                result = latest_result(session, row.id)
                can_publish = result is not None and result.calculation["final_score"] is not None
                if action == "publish" and not can_publish:
                    raise APIError(
                        409, "INSUFFICIENT_BALLOTS", "未达到最低份数，请补评或标记无结果"
                    )
                if action == "no-result" and can_publish:
                    raise APIError(409, "RESULT_AVAILABLE", "任务已形成成绩，不能标记无结果")
                row.status = "PUBLISHED" if action == "publish" else "NO_RESULT"
                if action == "publish":
                    row.published_at = now
            record_change(
                session,
                event,
                row,
                owner_id,
                {
                    "reopen": "round.reopened",
                    "publish": "result.published",
                    "no-result": "round.no_result",
                }[action],
                before,
                reason,
                request_id,
                now,
            )
        session.flush()
        result = state(event, row, now)
    return result


def lifecycle(database, owner_id, event_id, action, body, request_id, clock):
    with database.transaction() as session:
        event = owned_event(session, owner_id, event_id, write=True, draft_only=False)
        if event.version != body.expected_version:
            raise APIError(409, "VERSION_CONFLICT", "活动版本已变化，请刷新后确认")
        if action == "finish":
            if event.status not in {"READY", "RUNNING"}:
                raise APIError(409, "EVENT_STATE_CONFLICT", "活动当前不能结束")
            pending = list(
                session.scalars(
                    select(ScoringRound.id)
                    .where(
                        ScoringRound.event_id == event.id,
                        ScoringRound.status.not_in(("PUBLISHED", "SKIPPED", "NO_RESULT")),
                    )
                    .order_by(ScoringRound.id)
                )
            )
            if pending:
                raise APIError(409, "UNFINISHED_ROUNDS", "待处理任务：" + ",".join(pending))
        elif event.status != "FINISHED":
            raise APIError(409, "EVENT_STATE_CONFLICT", "仅已结束活动可以归档")
        before = {"status": event.status, "version": event.version}
        event.status = "FINISHED" if action == "finish" else "ARCHIVED"
        record_change(
            session,
            event,
            None,
            owner_id,
            f"event.{event.status.lower()}",
            before,
            None,
            request_id,
            clock(),
        )
        session.flush()
        result = EventInfo.model_validate(event)
    return result


def history(database, owner_id, round_id):
    with database.transaction() as session:
        owned_round(session, owner_id, round_id, write=True)
        return {
            "snapshots": [
                ResultInfo.model_validate(r)
                for r in session.scalars(
                    select(ResultSnapshot)
                    .where(ResultSnapshot.round_id == round_id)
                    .order_by(ResultSnapshot.round_version)
                )
            ]
        }


def ranking(session, event_id):
    rows = list(
        session.execute(
            select(ScoringRound, Entry)
            .join(Entry, Entry.id == ScoringRound.entry_id)
            .where(ScoringRound.event_id == event_id, ScoringRound.status == "PUBLISHED")
            .order_by(Entry.sort_order, Entry.number, Entry.id)
        )
    )
    entries = {e.id: e for _, e in rows}
    ranked = rank_results(
        [
            RankingEntry(
                e.id, latest_result(session, r.id).calculation["final_score"], e.sort_order, True
            )
            for r, e in rows
        ]
    )
    return [
        RankingInfo(
            entry_id=r.entry_id,
            number=entries[r.entry_id].number,
            name=entries[r.entry_id].name,
            final_score=format(r.final_score, ".2f"),
            rank=r.rank,
        )
        for r in ranked
    ]


def read_ranking(database, owner_id, event_id):
    with database.transaction() as session:
        owned_event(session, owner_id, event_id, write=True, draft_only=False)
        return ranking(session, event_id)
