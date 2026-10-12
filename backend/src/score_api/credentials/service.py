"""凭证写入与脱敏审计同事务；慢哈希在数据库连接之外执行。"""

from sqlalchemy import select

from score_api.core.errors import APIError
from score_api.credentials.schemas import CredentialResult
from score_api.credentials.security import prepare_credential
from score_api.events.models import EventJudge
from score_api.events.service import audit, get_member, owned_event


def credential_metadata(judge):
    return {
        "credential_source": judge.credential_source,
        "credential_version": judge.credential_version,
        "credential_updated_at": (
            judge.credential_updated_at.isoformat() if judge.credential_updated_at else None
        ),
    }


def apply_credential(session, event, judge, prepared, owner_id, request_id, now):
    before = credential_metadata(judge)
    judge.credential_hash = prepared.encoded
    judge.credential_lookup = prepared.lookup
    judge.credential_source = prepared.source
    judge.credential_version += 1
    judge.credential_updated_at = now
    event.updated_at = now
    session.flush()
    audit(
        session,
        event,
        owner_id,
        "credential.set",
        judge.id,
        before,
        credential_metadata(judge),
        request_id,
        now,
    )
    return CredentialResult(
        event_id=event.id,
        judge_id=judge.id,
        code=prepared.code,
        credential_source=judge.credential_source,
        credential_version=judge.credential_version,
        credential_updated_at=now,
    )


def set_credential(database, settings, owner_id, event_id, judge_id, body, request_id, clock):
    # 权限先于高成本计算检查；提交时再次锁内检查，阻止与发布竞争。
    with database.transaction() as session:
        event = owned_event(session, owner_id, event_id)
        if event.status != "DRAFT":
            raise APIError(409, "EVENT_NOT_DRAFT", "仅允许设置草稿活动身份码")
        get_member(session, EventJudge, event_id, judge_id)
    manual = body.code.get_secret_value() if body.code is not None else None
    for _ in range(5):
        prepared = prepare_credential(settings, event_id, manual)
        with database.transaction() as session:
            event = owned_event(session, owner_id, event_id, write=True)
            judge = get_member(session, EventJudge, event_id, judge_id)
            duplicate = session.scalar(
                select(EventJudge.id).where(
                    EventJudge.event_id == event_id,
                    EventJudge.credential_lookup == prepared.lookup,
                    EventJudge.id != judge_id,
                )
            )
            if duplicate:
                if manual is not None:
                    raise APIError(409, "CREDENTIAL_CONFLICT", "该身份码已被本活动使用")
                continue
            result = apply_credential(
                session, event, judge, prepared, owner_id, request_id, clock()
            )
        return result
    raise APIError(503, "CREDENTIAL_GENERATION_BUSY", "身份码生成失败，请重试", retry_after=1)
