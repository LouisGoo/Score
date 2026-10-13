"""原子发布与复制；冻结规则/名单不包含任何凭证或会话。"""

import secrets
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from score_api.core.errors import APIError
from score_api.credentials.security import ALPHABET, credential_key, prepare_credential
from score_api.credentials.service import apply_credential
from score_api.events.models import Entry, Event, EventJudge, EventSnapshot
from score_api.events.publication_schemas import (
    FrozenJudge,
    PublicationInfo,
    PublishResult,
    RoundInfo,
    SnapshotInfo,
)
from score_api.events.schemas import EntryInfo, EventCreate, EventInfo, RuleInput
from score_api.events.service import audit, owned_event
from score_api.rounds.models import RoundJudge, ScoringRound
from score_api.scoring import Criterion, ScoringRule


def members(session, event_id):
    entries = list(
        session.scalars(
            select(Entry)
            .where(Entry.event_id == event_id)
            .order_by(Entry.sort_order, Entry.number, Entry.id)
        )
    )
    judges = list(
        session.scalars(
            select(EventJudge)
            .where(EventJudge.event_id == event_id)
            .order_by(EventJudge.number, EventJudge.id)
        )
    )
    return entries, judges


def validate_publication(event, entries, judges):
    if not entries or not judges or event.scoring_rule is None:
        raise APIError(422, "PUBLISH_INVALID", "发布需至少一个对象、一个评委及完整评分规则")
    try:
        rule = RuleInput.model_validate(event.scoring_rule)
        scoring = ScoringRule(
            criteria=tuple(
                Criterion(c.criterion_id, c.maximum, c.weight, c.step) for c in rule.criteria
            ),
            expected_count=len(judges),
            algorithm=rule.algorithm,
            minimum_ballots=rule.minimum_ballots,
        )
    except ValueError:
        raise APIError(422, "PUBLISH_INVALID", "规则或评委人数不满足算法及有效份数门槛") from None
    return {
        **rule.model_dump(mode="json"),
        "expected_count": len(judges),
        "minimum_ballots": scoring.minimum_ballots,
    }


def generate_public_code():
    return "".join(secrets.choice(ALPHABET) for _ in range(12))


def assign_public_code(session, event):
    for _ in range(5):
        try:
            with session.begin_nested():
                event.public_code = generate_public_code()
                session.flush()
            return
        except IntegrityError as exc:
            if exc.orig.args[0] != 1062:
                raise
    raise APIError(503, "PUBLIC_CODE_BUSY", "活动码生成失败，请重试", retry_after=1)


def publish_event(database, settings, owner_id, event_id, request_id, clock):
    with database.transaction() as session:
        event = owned_event(session, owner_id, event_id)
        if event.status != "DRAFT":
            raise APIError(409, "EVENT_NOT_DRAFT", "活动已发布")
        entries, judges = members(session, event_id)
        validate_publication(event, entries, judges)
        missing = [j.id for j in judges if not j.credential_is_set]
        occupied = {j.credential_lookup for j in judges if j.credential_is_set}
    credential_key(settings)
    prepared = {}
    # 批量慢哈希不占连接、不持有活动锁。锁内重新验证新增或修改的名单。
    for judge_id in missing:
        for _ in range(5):
            candidate = prepare_credential(settings, event_id, None)
            if candidate.lookup not in occupied:
                prepared[judge_id] = candidate
                occupied.add(candidate.lookup)
                break
        else:
            raise APIError(
                503, "CREDENTIAL_GENERATION_BUSY", "身份码生成失败，请重试", retry_after=1
            )
    with database.transaction() as session:
        event = owned_event(session, owner_id, event_id, write=True)
        entries, judges = members(session, event_id)
        rule = validate_publication(event, entries, judges)
        occupied = {j.credential_lookup for j in judges if j.credential_is_set}
        now = clock()
        generated = []
        for judge in judges:
            if judge.credential_is_set:
                continue
            candidate = prepared.get(judge.id)
            if candidate is None or candidate.lookup in occupied:
                raise APIError(409, "PUBLISH_CONFLICT", "发布准备期间名单或凭证已变化，请重新发布")
            generated.append(
                apply_credential(session, event, judge, candidate, owner_id, request_id, now)
            )
            occupied.add(candidate.lookup)
        snapshot = EventSnapshot(
            id=uuid4().hex,
            event_id=event_id,
            rule_version=1,
            scoring_rule=rule,
            entries=[EntryInfo.model_validate(e).model_dump(mode="json") for e in entries],
            judges=[FrozenJudge.model_validate(j).model_dump(mode="json") for j in judges],
            duration_seconds=event.duration_seconds,
            allow_revisions=event.allow_revisions,
            created_at=now,
        )
        session.add(snapshot)
        session.flush()
        rounds = [
            ScoringRound(id=uuid4().hex, event_id=event_id, entry_id=e.id, rule_id=snapshot.id)
            for e in entries
        ]
        session.add_all(rounds)
        session.flush()
        session.add_all(
            [
                RoundJudge(round_id=r.id, event_judge_id=j.id, event_id=event_id)
                for r in rounds
                for j in judges
            ]
        )
        assign_public_code(session, event)
        event.status, event.published_at, event.updated_at = "READY", now, now
        event.version += 1
        # 首份角色快照的版本从 1 开始，各角色后续独立递增。
        event.screen_version = 1
        for judge in judges:
            judge.snapshot_version = 1
        audit(
            session,
            event,
            owner_id,
            "event.published",
            event_id,
            {"status": "DRAFT"},
            {"status": "READY", "snapshot_id": snapshot.id, "rule_version": 1},
            request_id,
            now,
        )
        result = PublishResult(
            event=EventInfo.model_validate(event),
            snapshot=SnapshotInfo.model_validate(snapshot),
            rounds=[RoundInfo.model_validate(r) for r in rounds],
            generated_credentials=generated,
        )
    return result


def read_publication(database, owner_id, event_id):
    with database.transaction() as session:
        event = owned_event(session, owner_id, event_id)
        snapshot = session.scalar(select(EventSnapshot).where(EventSnapshot.event_id == event_id))
        if snapshot is None:
            raise APIError(404, "NOT_FOUND", "活动尚未发布")
        rounds = session.scalars(
            select(ScoringRound).where(ScoringRound.event_id == event_id).order_by(ScoringRound.id)
        )
        return PublicationInfo(
            event=EventInfo.model_validate(event),
            snapshot=SnapshotInfo.model_validate(snapshot),
            rounds=[RoundInfo.model_validate(r) for r in rounds],
        )


def copy_event(database, owner_id, event_id, request_id, clock):
    with database.transaction() as session:
        source = owned_event(session, owner_id, event_id, write=True, draft_only=False)
        entries, judges = members(session, event_id)
        values = {name: getattr(source, name) for name in EventCreate.model_fields}
        now = clock()
        event = Event(
            id=uuid4().hex,
            owner_id=owner_id,
            status="DRAFT",
            created_at=now,
            updated_at=now,
            **values,
        )
        session.add(event)
        session.flush()
        session.add_all(
            [
                Entry(
                    id=uuid4().hex,
                    event_id=event.id,
                    number=e.number,
                    name=e.name,
                    description=e.description,
                    sort_order=e.sort_order,
                )
                for e in entries
            ]
        )
        session.add_all(
            [
                EventJudge(id=uuid4().hex, event_id=event.id, number=j.number, name=j.name)
                for j in judges
            ]
        )
        audit(
            session,
            event,
            owner_id,
            "event.copied",
            event.id,
            None,
            {"source_event_id": source.id},
            request_id,
            now,
        )
        result = EventInfo.model_validate(event)
    return result
