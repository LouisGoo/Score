"""在单一读视图中无锁读取一致快照；各角色显式构造白名单响应。"""

import secrets
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select

from score_api.ballots.models import Ballot, BallotRevision
from score_api.ballots.service import make_receipt
from score_api.core.errors import APIError
from score_api.core.security import TOKEN_PATTERN, token_hash
from score_api.events.models import Entry, Event, EventJudge, EventSnapshot
from score_api.events.schemas import EntryInfo, EventInfo, JudgeInfo
from score_api.events.service import audit, owned_event
from score_api.judge_sessions.service import lock_principal
from score_api.outbox.service import record
from score_api.results.models import ResultSnapshot
from score_api.results.schemas import BallotHistory, RankingInfo, ResultInfo
from score_api.rounds.models import RoundJudge, ScoringRound
from score_api.scoring import RankingEntry, rank_results
from score_api.snapshots.models import ScreenGrant
from score_api.snapshots.schemas import (
    AdminSnapshot,
    CreatedGrant,
    GrantInfo,
    JudgeIdentity,
    JudgeSnapshot,
    PublicEvent,
    PublicRound,
    PublishedResult,
    ScreenDisplay,
    ScreenSnapshot,
)


def require_published(event):
    if event.status == "DRAFT":
        raise APIError(409, "EVENT_NOT_PUBLISHED", "活动尚未发布")


def public_event(event):
    return PublicEvent(**{k: getattr(event, k) for k in PublicEvent.model_fields})


def display(event):
    return ScreenDisplay(
        mode=event.screen_mode,
        round_id=event.screen_round_id,
        title=event.screen_title or event.title,
        theme=event.screen_theme,
        show_public_qr=event.show_public_qr,
        leaderboard_limit=event.leaderboard_limit,
    )


def public_data(session, event):
    entries = list(
        session.scalars(
            select(Entry)
            .where(Entry.event_id == event.id)
            .order_by(Entry.sort_order, Entry.number, Entry.id)
        )
    )
    entry_map = {e.id: e for e in entries}
    rows = list(session.scalars(select(ScoringRound).where(ScoringRound.event_id == event.id)))
    rows.sort(key=lambda r: (entry_map[r.entry_id].sort_order, entry_map[r.entry_id].number, r.id))
    submitted = dict(
        session.execute(
            select(Ballot.round_id, func.count())
            .where(Ballot.event_id == event.id)
            .group_by(Ballot.round_id)
        ).all()
    )
    expected = dict(
        session.execute(
            select(RoundJudge.round_id, func.count())
            .where(RoundJudge.event_id == event.id)
            .group_by(RoundJudge.round_id)
        ).all()
    )
    results = list(
        session.scalars(
            select(ResultSnapshot)
            .where(ResultSnapshot.event_id == event.id)
            .order_by(ResultSnapshot.round_version, ResultSnapshot.id)
        )
    )
    latest = {r.round_id: r for r in results}
    rounds, published = [], []
    for row in rows:
        entry = entry_map[row.entry_id]
        rounds.append(
            PublicRound(
                id=row.id,
                entry_id=entry.id,
                number=entry.number,
                name=entry.name,
                description=entry.description,
                status=row.status,
                version=row.version,
                submitted_count=submitted.get(row.id, 0),
                expected_count=expected[row.id],
                deadline_at=row.deadline_at,
                remaining_seconds=row.remaining_seconds,
            )
        )
        if row.status == "PUBLISHED":
            calculation = latest[row.id].calculation
            published.append(
                PublishedResult(
                    round_id=row.id,
                    entry_id=entry.id,
                    number=entry.number,
                    name=entry.name,
                    published_at=row.published_at,
                    **{
                        k: calculation[k]
                        for k in (
                            "final_score",
                            "valid_count",
                            "expected_count",
                            "minimum_ballots",
                            "algorithm",
                            "rule_version",
                        )
                    },
                )
            )
    ranked = rank_results(
        [
            RankingEntry(r.entry_id, r.final_score, entry_map[r.entry_id].sort_order, True)
            for r in published
        ]
    )
    ranking = [
        RankingInfo(
            entry_id=r.entry_id,
            number=entry_map[r.entry_id].number,
            name=entry_map[r.entry_id].name,
            final_score=format(r.final_score, ".2f"),
            rank=r.rank,
        )
        for r in ranked
    ]
    return entries, rounds, results, published, ranking


def ballot_history(session, event_id, judge_id=None):
    query = (
        select(Ballot, BallotRevision)
        .join(BallotRevision, BallotRevision.ballot_id == Ballot.id)
        .where(Ballot.event_id == event_id)
    )
    if judge_id is not None:
        query = query.where(Ballot.judge_id == judge_id)
    grouped = {}
    for ballot, revision in session.execute(
        query.order_by(Ballot.judge_id, Ballot.id, BallotRevision.revision)
    ):
        grouped.setdefault(ballot.judge_id, []).append(make_receipt(ballot, revision))
    return [BallotHistory(judge_id=id_, receipts=receipts) for id_, receipts in grouped.items()]


def grant_list(session, event_id):
    return [
        GrantInfo.model_validate(g)
        for g in session.scalars(
            select(ScreenGrant)
            .where(ScreenGrant.event_id == event_id)
            .order_by(ScreenGrant.created_at, ScreenGrant.id)
        )
    ]


def admin_snapshot(database, owner_id, event_id, clock):
    with database.read_snapshot() as session:
        event = owned_event(session, owner_id, event_id, draft_only=False)
        require_published(event)
        snapshot = session.scalar(select(EventSnapshot).where(EventSnapshot.event_id == event_id))
        entries, rounds, results, _, ranking = public_data(session, event)
        result = AdminSnapshot(
            version=event.version,
            server_time=clock(),
            event=EventInfo.model_validate(event),
            rule_id=snapshot.id,
            rule_version=snapshot.rule_version,
            rule=snapshot.scoring_rule,
            entries=[EntryInfo.model_validate(e) for e in entries],
            judges=[
                JudgeInfo.model_validate(j)
                for j in session.scalars(
                    select(EventJudge)
                    .where(EventJudge.event_id == event_id)
                    .order_by(EventJudge.number)
                )
            ],
            rounds=rounds,
            results=[ResultInfo.model_validate(r) for r in results],
            ballots=ballot_history(session, event_id),
            ranking=ranking,
            display=display(event),
            screen_grants=grant_list(session, event_id),
        )
    return result


def judge_snapshot(database, principal, event_id, clock):
    if principal.event_id != event_id:
        raise APIError(404, "NOT_FOUND", "活动不存在")
    with database.read_snapshot() as session:
        event, judge, _ = lock_principal(session, principal, clock, write=False)
        snapshot = session.scalar(select(EventSnapshot).where(EventSnapshot.event_id == event_id))
        _, rounds, _, published, ranking = public_data(session, event)
        result = JudgeSnapshot(
            version=judge.snapshot_version,
            server_time=clock(),
            event=public_event(event),
            identity=JudgeIdentity(id=judge.id, name=judge.name, number=judge.number),
            rule_id=snapshot.id,
            rule_version=snapshot.rule_version,
            rule=snapshot.scoring_rule,
            allow_revisions=snapshot.allow_revisions,
            rounds=rounds,
            my_ballots=ballot_history(session, event_id, judge.id),
            published_results=published,
            ranking=ranking,
        )
    return result


def screen_snapshot(database, grant_id, token, clock):
    if not TOKEN_PATTERN.fullmatch(token):
        raise APIError(401, "SCREEN_GRANT_INVALID", "大屏授权无效或已到期")
    with database.read_snapshot() as session:
        grant = session.get(ScreenGrant, grant_id)
        event = session.get(Event, grant.event_id) if grant is not None else None
        now = clock()
        if (
            event is None
            or grant is None
            or grant.revoked_at is not None
            or grant.expires_at <= now
            or not secrets.compare_digest(grant.token_hash, token_hash(token))
        ):
            raise APIError(401, "SCREEN_GRANT_INVALID", "大屏授权无效或已到期")
        require_published(event)
        _, rounds, _, published, ranking = public_data(session, event)
        result = ScreenSnapshot(
            version=event.screen_version,
            server_time=now,
            event=public_event(event),
            display=display(event),
            current_round=next((r for r in rounds if r.id == event.screen_round_id), None),
            published_results=published,
            ranking=ranking[: event.leaderboard_limit],
        )
    return result


def record_screen_change(
    session, event, owner_id, action, target_id, before, after, request_id, now
):
    event.version += 1
    event.updated_at = now
    audit(session, event, owner_id, action, target_id, before, after, request_id, now)
    record(session, event, action, now, screen=action == "screen.changed")


def create_grant(database, owner_id, event_id, body, request_id, clock):
    token = secrets.token_urlsafe(32)
    with database.transaction() as session:
        event = owned_event(session, owner_id, event_id, write=True, draft_only=False)
        require_published(event)
        now = clock()
        active = session.scalar(
            select(func.count())
            .select_from(ScreenGrant)
            .where(
                ScreenGrant.event_id == event_id,
                ScreenGrant.revoked_at.is_(None),
                ScreenGrant.expires_at > now,
            )
        )
        if active >= 20:
            raise APIError(409, "SCREEN_GRANT_LIMIT", "最多同时存在 20 个大屏授权，请先撤销旧授权")
        grant = ScreenGrant(
            id=uuid4().hex,
            event_id=event_id,
            token_hash=token_hash(token),
            created_at=now,
            expires_at=now + timedelta(seconds=body.ttl_seconds),
        )
        session.add(grant)
        session.flush()
        info = GrantInfo.model_validate(grant)
        record_screen_change(
            session,
            event,
            owner_id,
            "screen.granted",
            grant.id,
            None,
            info.model_dump(mode="json"),
            request_id,
            now,
        )
        result = CreatedGrant(**info.model_dump(), token=token)
    return result


def list_grants(database, owner_id, event_id):
    with database.transaction() as session:
        owned_event(session, owner_id, event_id, write=True, draft_only=False)
        return grant_list(session, event_id)


def revoke_grant(database, owner_id, event_id, grant_id, request_id, clock):
    with database.transaction() as session:
        event = owned_event(session, owner_id, event_id, write=True, draft_only=False)
        grant = session.scalar(
            select(ScreenGrant)
            .where(ScreenGrant.event_id == event_id, ScreenGrant.id == grant_id)
            .with_for_update()
        )
        if grant is None:
            raise APIError(404, "NOT_FOUND", "大屏授权不存在")
        if grant.revoked_at is not None:
            return
        now = clock()
        grant.revoked_at = now
        record_screen_change(
            session,
            event,
            owner_id,
            "screen.revoked",
            grant.id,
            None,
            {"revoked_at": now.isoformat()},
            request_id,
            now,
        )


def change_display(database, owner_id, event_id, body, request_id, clock):
    with database.transaction() as session:
        event = owned_event(session, owner_id, event_id, write=True, draft_only=False)
        require_published(event)
        if body.expected_version != event.version:
            raise APIError(409, "VERSION_CONFLICT", "活动版本已变化，请刷新后确认")
        if body.round_id is not None:
            row = session.scalar(
                select(ScoringRound).where(
                    ScoringRound.event_id == event_id, ScoringRound.id == body.round_id
                )
            )
            if row is None:
                raise APIError(404, "NOT_FOUND", "评分任务不存在")
            required = {"progress": "OPEN", "paused": "PAUSED", "result": "PUBLISHED"}
            if row.status != required[body.mode]:
                raise APIError(409, "DISPLAY_STATE_CONFLICT", "任务状态不允许此展示模式")
        if body.mode == "ended" and event.status not in {"FINISHED", "ARCHIVED"}:
            raise APIError(409, "DISPLAY_STATE_CONFLICT", "活动尚未结束")
        before = display(event).model_dump(mode="json")
        event.screen_mode, event.screen_round_id = body.mode, body.round_id
        event.screen_title, event.screen_theme = body.title, body.theme
        event.show_public_qr, event.leaderboard_limit = body.show_public_qr, body.leaderboard_limit
        event.screen_version += 1
        result = display(event)
        record_screen_change(
            session,
            event,
            owner_id,
            "screen.changed",
            event.id,
            before,
            result.model_dump(mode="json"),
            request_id,
            clock(),
        )
    return result
