"""验证与会话交换分开；活动 → 评委 → 确认令牌/会话的固定加锁顺序。"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select, text

from score_api.auth.service import consume_limits
from score_api.core.errors import APIError
from score_api.core.security import DUMMY_HASH, TOKEN_PATTERN, token_hash, verify_password
from score_api.credentials.security import credential_key, credential_lookup
from score_api.events.models import Event, EventJudge
from score_api.events.publication_schemas import FrozenJudge
from score_api.judge_sessions.models import JudgeAuthAudit, JudgeConfirmation, JudgeSession
from score_api.judge_sessions.schemas import ConfirmationInfo, JudgeSessionInfo, PreviewInfo


def judge_csrf(token):
    return token_hash("score-judge-csrf:" + token)


@dataclass(frozen=True)
class JudgePrincipal:
    event_id: str
    judge_id: str
    token_hash: str = field(repr=False)
    info: JudgeSessionInfo


def auth_audit(session, event_id, judge_id, action, request_id, now):
    session.add(
        JudgeAuthAudit(
            id=uuid4().hex,
            event_id=event_id,
            judge_id=judge_id,
            action=action,
            request_id=request_id,
            created_at=now,
        )
    )


def event_for_code(session, code):
    event = session.scalar(select(Event).where(Event.public_code == code, Event.status != "DRAFT"))
    if event is None:
        raise APIError(404, "NOT_FOUND", "活动不存在")
    return event


def check_exchange_open(event):
    if event.status not in {"READY", "RUNNING"}:
        raise APIError(409, "EVENT_CLOSED", "活动已停止身份兑换")


def preview(database, code):
    with database.transaction() as session:
        event = event_for_code(session, code)
        return PreviewInfo(
            public_code=event.public_code,
            title=event.title,
            description=event.description,
            organization=event.organization,
            planned_at=event.planned_at,
            status=event.status,
            exchange_open=event.status in {"READY", "RUNNING"},
        )


def verify_identity(database, settings, clock, source, body, bootstrap, request_id):
    code = body.code.get_secret_value()
    attempt = hmac.new(
        credential_key(settings), (body.public_code + "\0" + code).encode("ascii"), hashlib.sha256
    ).hexdigest()
    consume_limits(
        database,
        clock(),
        settings.judge_limit_window_seconds,
        (
            ("judge_source", source, settings.judge_source_limit),
            ("judge_event", body.public_code, settings.judge_event_limit),
            ("judge_attempt", attempt, settings.judge_attempt_limit),
        ),
    )
    with database.transaction() as session:
        event = event_for_code(session, body.public_code)
        check_exchange_open(event)
        event_id = event.id
        lookup = credential_lookup(settings, event_id, code)
        judge = session.scalar(
            select(EventJudge).where(
                EventJudge.event_id == event_id, EventJudge.credential_lookup == lookup
            )
        )
        judge_id = judge.id if judge else None
        encoded = judge.credential_hash if judge else DUMMY_HASH
        version = judge.credential_version if judge else None
    valid = verify_password(code, encoded)
    with database.transaction() as session:
        event = session.scalar(select(Event).where(Event.id == event_id).with_for_update())
        check_exchange_open(event)
        judge = session.scalar(
            select(EventJudge)
            .where(EventJudge.id == judge_id, EventJudge.event_id == event_id)
            .with_for_update()
        )
        now = clock()
        accepted = (
            valid
            and judge is not None
            and judge.credential_hash == encoded
            and judge.credential_lookup == lookup
            and judge.credential_version == version
        )
        if not accepted:
            auth_audit(session, event_id, judge_id, "verify_failed", request_id, now)
        else:
            # 只清理短期确认令牌；会话和审计不在这里静默删除。
            session.execute(
                text("DELETE FROM score_judge_confirmations WHERE expires_at <= :now LIMIT 100"),
                {"now": now.replace(tzinfo=None)},
            )
            token = secrets.token_urlsafe(32)
            expires_at = now + timedelta(seconds=settings.judge_confirmation_ttl_seconds)
            session.add(
                JudgeConfirmation(
                    token_hash=token_hash(token),
                    event_id=event_id,
                    judge_id=judge.id,
                    credential_version=version,
                    bootstrap_hash=token_hash(bootstrap),
                    expires_at=expires_at,
                )
            )
            auth_audit(session, event_id, judge.id, "identity_verified", request_id, now)
            result = ConfirmationInfo(
                judge=FrozenJudge.model_validate(judge),
                confirmation_token=token,
                expires_at=expires_at,
            )
    if not accepted:
        raise APIError(401, "INVALID_CREDENTIALS", "身份码无效")
    return result


def session_info(row, judge, event, token):
    return JudgeSessionInfo(
        judge=FrozenJudge.model_validate(judge),
        expires_at=row.expires_at,
        csrf_token=judge_csrf(token),
        read_only=event.status in {"FINISHED", "ARCHIVED"},
    )


def session_row(session, token, now):
    if not TOKEN_PATTERN.fullmatch(token):
        return None
    return session.execute(
        select(JudgeSession, EventJudge, Event)
        .join(
            EventJudge,
            (EventJudge.id == JudgeSession.judge_id)
            & (EventJudge.event_id == JudgeSession.event_id),
        )
        .join(Event, Event.id == JudgeSession.event_id)
        .where(
            JudgeSession.token_hash == token_hash(token),
            JudgeSession.revoked_at.is_(None),
            JudgeSession.expires_at > now,
            JudgeSession.credential_version == EventJudge.credential_version,
            Event.status != "DRAFT",
        )
    ).one_or_none()


def get_principal(database, token, now):
    with database.transaction() as session:
        found = session_row(session, token, now)
        if found is None:
            raise APIError(401, "SESSION_EXPIRED", "会话已失效，请重新验证身份")
        row, judge, event = found
        return JudgePrincipal(
            event.id, judge.id, row.token_hash, session_info(row, judge, event, token)
        )


def exchange(database, settings, clock, source, body, bootstrap, old_token, request_id):
    consume_limits(
        database,
        clock(),
        settings.judge_limit_window_seconds,
        (("judge_source", source, settings.judge_source_limit),),
    )
    digest = token_hash(body.confirmation_token.get_secret_value())
    with database.transaction() as session:
        initial = session.get(JudgeConfirmation, digest)
        if initial is None:
            raise APIError(401, "CONFIRMATION_EXPIRED", "身份确认已失效，请重新验证")
        event = session.scalar(select(Event).where(Event.id == initial.event_id).with_for_update())
        check_exchange_open(event)
        judge = session.scalar(
            select(EventJudge)
            .where(EventJudge.id == initial.judge_id, EventJudge.event_id == event.id)
            .with_for_update()
        )
        confirmation = session.scalar(
            select(JudgeConfirmation)
            .where(JudgeConfirmation.token_hash == digest)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        now = clock()
        if (
            confirmation is None
            or confirmation.expires_at <= now
            or confirmation.consumed_at is not None
            or confirmation.credential_version != judge.credential_version
            or confirmation.bootstrap_hash != token_hash(bootstrap)
        ):
            raise APIError(401, "CONFIRMATION_EXPIRED", "身份确认已失效，请重新验证")
        browser_session = session_row(session, old_token, now)
        if browser_session is not None and browser_session[0].judge_id != judge.id:
            raise APIError(409, "SESSION_SWITCH_REQUIRED", "请先退出当前评委身份后再切换")
        active = session.scalar(
            select(JudgeSession)
            .where(JudgeSession.judge_id == judge.id, JudgeSession.revoked_at.is_(None))
            .with_for_update()
        )
        if active is not None and (
            active.expires_at <= now or active.credential_version != judge.credential_version
        ):
            active.revoked_at = now
            session.flush()
            active = None
        if active is not None:
            if not TOKEN_PATTERN.fullmatch(old_token) or active.token_hash != token_hash(old_token):
                raise APIError(
                    409, "JUDGE_SESSION_ACTIVE", "此评委已有有效会话，换机请联系主办方重置身份码"
                )
            token = old_token
        else:
            token = secrets.token_urlsafe(32)
            active = JudgeSession(
                token_hash=token_hash(token),
                event_id=event.id,
                judge_id=judge.id,
                credential_version=judge.credential_version,
                created_at=now,
                expires_at=now + timedelta(seconds=settings.judge_session_ttl_seconds),
            )
            session.add(active)
        confirmation.consumed_at = now
        auth_audit(session, event.id, judge.id, "session_exchanged", request_id, now)
        result = session_info(active, judge, event, token)
    return token, result


def lock_principal(session, principal, clock, write=True):
    """业务写事务应复用：取得活动/评委锁后再次验证会话，阻止与重置竞争。

    write=False 仅供只读快照，在同一读视图中校验会话而不加锁。
    """

    def load(query):
        if write:
            query = query.with_for_update()
        return session.scalar(query.execution_options(populate_existing=True))

    event = load(select(Event).where(Event.id == principal.event_id))
    judge = load(
        select(EventJudge).where(
            EventJudge.id == principal.judge_id, EventJudge.event_id == principal.event_id
        )
    )
    row = load(select(JudgeSession).where(JudgeSession.token_hash == principal.token_hash))
    if (
        row is None
        or judge is None
        or event is None
        or event.status == "DRAFT"
        or row.event_id != principal.event_id
        or row.judge_id != principal.judge_id
        or row.revoked_at is not None
        or row.expires_at <= clock()
        or row.credential_version != judge.credential_version
    ):
        raise APIError(401, "SESSION_EXPIRED", "会话已失效，请重新验证身份")
    return event, judge, row


def logout(database, principal, clock, request_id):
    with database.transaction() as session:
        event, judge, row = lock_principal(session, principal, clock)
        now = clock()
        row.revoked_at = now
        auth_audit(session, event.id, judge.id, "logout", request_id, now)
