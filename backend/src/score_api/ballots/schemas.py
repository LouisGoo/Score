from datetime import datetime

from pydantic import Field

from score_api.events.schemas import DecimalString, InputModel, Number


class ScoreInput(InputModel):
    criterion_id: Number
    value: DecimalString


class BallotInput(InputModel):
    rule_version: int = Field(strict=True, ge=1, le=2147483647)
    expected_ballot_revision: int = Field(strict=True, ge=0, le=2147483646)
    scores: list[ScoreInput] = Field(min_length=1, max_length=20)


class BallotReceipt(InputModel):
    ballot_id: str
    receipt_id: str
    round_id: str
    revision: int
    rule_version: int
    scores: list[ScoreInput]
    total_score: str
    accepted_at: datetime
