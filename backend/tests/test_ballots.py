import pytest
from pydantic import ValidationError

from score_api.ballots.schemas import BallotInput
from score_api.core.config import Settings
from score_api.main import create_app


@pytest.mark.parametrize(
    "field,value",
    [
        ("rule_version", True),
        ("rule_version", 0),
        ("rule_version", "1"),
        ("expected_ballot_revision", True),
        ("expected_ballot_revision", -1),
        ("expected_ballot_revision", "0"),
        ("expected_ballot_revision", 2147483647),
    ],
)
def test_versions_are_bounded_strict_integers(field, value):
    body = {
        "rule_version": 1,
        "expected_ballot_revision": 0,
        "scores": [{"criterion_id": "total", "value": "0"}],
        field: value,
    }
    with pytest.raises(ValidationError):
        BallotInput.model_validate(body)


def test_openapi_declares_key_and_private_receipt():
    app = create_app(Settings(_env_file=None, DATABASE_URL=None))
    spec = app.openapi()
    path = spec["paths"]["/api/v1/rounds/{round_id}/my-ballot"]
    for method, required in (("put", True), ("get", False)):
        header = next(p for p in path[method]["parameters"] if p["name"] == "Idempotency-Key")
        assert header["required"] is required and header["in"] == "header"
    fields = spec["components"]["schemas"]["BallotReceipt"]["properties"]
    assert set(fields) == {
        "ballot_id",
        "receipt_id",
        "round_id",
        "revision",
        "rule_version",
        "scores",
        "total_score",
        "accepted_at",
    }
