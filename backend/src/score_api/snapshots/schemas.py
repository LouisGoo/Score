from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from score_api.events.publication_schemas import PublishedRule
from score_api.events.schemas import (
    EntryInfo,
    EventInfo,
    InputModel,
    JudgeInfo,
    PositiveCount,
    ScreenTitle,
)
from score_api.results.schemas import BallotHistory, RankingInfo, ResultInfo
from score_api.rounds.schemas import ControlInput


class PublicEvent(InputModel):
    id: str
    title: str
    description: str
    organization: str
    status: Literal["READY", "RUNNING", "FINISHED", "ARCHIVED"]
    public_code: str


class PublishedResult(InputModel):
    round_id: str
    entry_id: str
    number: str
    name: str
    final_score: str
    valid_count: int
    expected_count: int
    minimum_ballots: int
    algorithm: Literal["mean", "trimmed_mean"]
    rule_version: int
    published_at: datetime


class PublicRound(InputModel):
    id: str
    entry_id: str
    number: str
    name: str
    description: str
    status: Literal["PENDING", "OPEN", "PAUSED", "CLOSED", "PUBLISHED", "SKIPPED", "NO_RESULT"]
    version: int
    submitted_count: int
    expected_count: int
    deadline_at: datetime | None
    remaining_seconds: Decimal | None


class JudgeIdentity(InputModel):
    id: str
    name: str
    number: str


class ScreenSettings(ControlInput):
    mode: Literal["waiting", "progress", "paused", "result", "leaderboard", "ended"]
    round_id: str | None = None
    title: ScreenTitle
    theme: Literal["light", "dark"]
    show_public_qr: bool = Field(strict=True)
    leaderboard_limit: PositiveCount

    @model_validator(mode="after")
    def target(self):
        if (self.mode in {"progress", "paused", "result"}) != (self.round_id is not None):
            raise ValueError("此展示模式需要匹配的任务 ID")
        return self


class ScreenDisplay(InputModel):
    mode: Literal["waiting", "progress", "paused", "result", "leaderboard", "ended"]
    round_id: str | None
    title: str
    theme: Literal["light", "dark"]
    show_public_qr: bool
    leaderboard_limit: int


class GrantInput(InputModel):
    ttl_seconds: int = Field(default=86400, strict=True, ge=60, le=2592000)


class GrantInfo(InputModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_id: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


class CreatedGrant(GrantInfo):
    token: str


class AdminSnapshot(InputModel):
    role: Literal["admin"] = "admin"
    version: int
    server_time: datetime
    event: EventInfo
    rule_id: str
    rule_version: int
    rule: PublishedRule
    entries: list[EntryInfo]
    judges: list[JudgeInfo]
    rounds: list[PublicRound]
    results: list[ResultInfo]
    ballots: list[BallotHistory]
    ranking: list[RankingInfo]
    display: ScreenDisplay
    screen_grants: list[GrantInfo]


class JudgeSnapshot(InputModel):
    role: Literal["judge"] = "judge"
    version: int
    server_time: datetime
    event: PublicEvent
    identity: JudgeIdentity
    rule_id: str
    rule_version: int
    rule: PublishedRule
    allow_revisions: bool
    rounds: list[PublicRound]
    my_ballots: list[BallotHistory]
    published_results: list[PublishedResult]
    ranking: list[RankingInfo]


class ScreenSnapshot(InputModel):
    role: Literal["screen"] = "screen"
    version: int
    server_time: datetime
    event: PublicEvent
    display: ScreenDisplay
    current_round: PublicRound | None
    published_results: list[PublishedResult]
    ranking: list[RankingInfo]
