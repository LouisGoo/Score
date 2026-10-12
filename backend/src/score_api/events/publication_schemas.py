from datetime import datetime

from pydantic import ConfigDict

from score_api.credentials.schemas import CredentialResult
from score_api.events.schemas import EntryInfo, EventInfo, InputModel, JudgeCreate, RuleInput


class FrozenJudge(JudgeCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_id: str


class PublishedRule(RuleInput):
    expected_count: int
    minimum_ballots: int


class SnapshotInfo(InputModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_id: str
    rule_version: int
    scoring_rule: PublishedRule
    entries: list[EntryInfo]
    judges: list[FrozenJudge]
    duration_seconds: int | None
    allow_revisions: bool
    created_at: datetime


class RoundInfo(InputModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_id: str
    entry_id: str
    rule_id: str
    status: str
    version: int


class PublicationInfo(InputModel):
    event: EventInfo
    snapshot: SnapshotInfo
    rounds: list[RoundInfo]


class PublishResult(PublicationInfo):
    generated_credentials: list[CredentialResult]
