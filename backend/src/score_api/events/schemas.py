"""草稿输入/输出；缺省与显式 null 区分，拒绝客户端设置归属及状态。"""

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from score_api.scoring import Criterion, ScoringRule

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Number = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Organization = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]
ScreenTitle = Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)]
DecimalString = Annotated[str, StringConstraints(pattern=r"^[0-9]{1,9}(\.[0-9]{1,6})?$")]
Duration = Annotated[int, Field(strict=True, ge=1, le=86400)]
PositiveCount = Annotated[int, Field(strict=True, ge=1, le=10000)]
SortOrder = Annotated[int, Field(strict=True, ge=0, le=2147483647)]
PlannedAt = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(timezone.utc))]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CriterionInput(InputModel):
    criterion_id: Number
    name: Title
    maximum: DecimalString = "100"
    weight: DecimalString = "1"
    step: DecimalString = "0.1"


class RuleInput(InputModel):
    mode: Literal["single", "multi"] = "single"
    criteria: list[CriterionInput] = Field(min_length=1, max_length=20)
    algorithm: Literal["mean", "trimmed_mean"] = "mean"
    minimum_ballots: PositiveCount | None = None

    @model_validator(mode="after")
    def valid_rule(self):
        if (self.mode == "single" and len(self.criteria) != 1) or (
            self.mode == "multi" and len(self.criteria) < 2
        ):
            raise ValueError("评分模式与维度数量不符")
        # 草稿可先设置规则再录入名单；实际 N/K 校验在发布时进行。
        ScoringRule(
            criteria=tuple(
                Criterion(c.criterion_id, c.maximum, c.weight, c.step) for c in self.criteria
            ),
            expected_count=max(5, self.minimum_ballots or 1),
            algorithm=self.algorithm,
            minimum_ballots=self.minimum_ballots,
        )
        return self


class EventCreate(InputModel):
    title: Title
    description: Description = ""
    organization: Organization = ""
    planned_at: PlannedAt | None = None
    scoring_rule: RuleInput | None = None
    duration_seconds: Duration | None = None
    allow_revisions: bool = Field(default=True, strict=True)
    screen_title: ScreenTitle = ""
    screen_theme: Literal["light", "dark"] = "light"
    show_public_qr: bool = Field(default=True, strict=True)
    leaderboard_limit: PositiveCount = 10


class PatchModel(InputModel):
    @model_validator(mode="after")
    def reject_null_and_empty(self):
        if not self.model_fields_set:
            raise ValueError("至少提供一个待修改字段")
        nullable = {"planned_at", "scoring_rule", "duration_seconds"}
        if any(getattr(self, key) is None for key in self.model_fields_set - nullable):
            raise ValueError("该字段不允许 null")
        return self


class EventPatch(PatchModel):
    title: Title | None = None
    description: Description | None = None
    organization: Organization | None = None
    planned_at: PlannedAt | None = None
    scoring_rule: RuleInput | None = None
    duration_seconds: Duration | None = None
    allow_revisions: bool | None = Field(default=None, strict=True)
    screen_title: ScreenTitle | None = None
    screen_theme: Literal["light", "dark"] | None = None
    show_public_qr: bool | None = Field(default=None, strict=True)
    leaderboard_limit: PositiveCount | None = None


class EventInfo(EventCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    owner_id: str
    status: Literal["DRAFT", "READY", "RUNNING", "FINISHED", "ARCHIVED"]
    public_code: str | None
    published_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class EntryCreate(InputModel):
    number: Number
    name: Title
    description: Description = ""
    sort_order: SortOrder = 0


class EntryPatch(PatchModel):
    number: Number | None = None
    name: Title | None = None
    description: Description | None = None
    sort_order: SortOrder | None = None


class EntryInfo(EntryCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_id: str


class JudgeCreate(InputModel):
    number: Number
    name: Title


class JudgePatch(PatchModel):
    number: Number | None = None
    name: Title | None = None


class JudgeInfo(JudgeCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_id: str
    credential_is_set: bool
    credential_source: Literal["generated", "manual"] | None
    credential_version: int
    credential_updated_at: datetime | None
