from datetime import datetime
from typing import Annotated, Literal

from pydantic import ConfigDict, StringConstraints

from score_api.ballots.schemas import BallotReceipt, ScoreInput
from score_api.events.schemas import Duration, InputModel
from score_api.rounds.schemas import ControlInput, SkipInput

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class CloseInput(ControlInput):
    reason: Reason | None = None


class ReopenInput(SkipInput):
    duration_seconds: Duration | None


class ResultBallot(InputModel):
    judge_id: str
    judge_number: str
    ballot_id: str
    receipt_id: str
    revision: int
    scores: list[ScoreInput]
    total: str
    exclusion: Literal["lowest", "highest"] | None


class Calculation(InputModel):
    rule_version: int
    algorithm: Literal["mean", "trimmed_mean"]
    valid_count: int
    expected_count: int
    minimum_ballots: int
    final_score: str | None
    ballots: list[ResultBallot]
    missing_judge_ids: list[str]


class ResultInfo(InputModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    round_id: str
    round_version: int
    rule_id: str
    calculation: Calculation
    reason: str | None
    source: Literal["manual", "deadline"]
    closed_at: datetime


class RankingInfo(InputModel):
    entry_id: str
    number: str
    name: str
    final_score: str
    rank: int


class ResultHistory(InputModel):
    snapshots: list[ResultInfo]


class BallotHistory(InputModel):
    judge_id: str
    receipts: list[BallotReceipt]
