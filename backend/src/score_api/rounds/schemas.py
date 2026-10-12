from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StringConstraints

from score_api.events.schemas import InputModel


class ControlInput(InputModel):
    expected_version: int = Field(strict=True, ge=1, le=2147483647)


class SkipInput(ControlInput):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class RoundInfo(InputModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_id: str
    entry_id: str
    rule_id: str
    status: Literal["PENDING", "OPEN", "PAUSED", "CLOSED", "PUBLISHED", "SKIPPED", "NO_RESULT"]
    version: int
    deadline_at: datetime | None
    remaining_seconds: Decimal | None


class RoundState(RoundInfo):
    server_time: datetime
    event_version: int
