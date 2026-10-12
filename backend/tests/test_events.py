import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from score_api.core.config import Settings
from score_api.events.schemas import EntryCreate, EventCreate, EventPatch, JudgePatch, RuleInput
from score_api.main import create_app


@pytest.mark.parametrize(
    "body",
    [
        {"title": " "},
        {"title": "x" * 81},
        {"title": "ok", "owner_id": "other"},
        {"title": "ok", "status": "READY"},
        {"title": "ok", "planned_at": "2026-10-12T12:00:00"},
        {"title": "ok", "duration_seconds": 0},
        {"title": "ok", "duration_seconds": True},
        {"title": "ok", "allow_revisions": "false"},
    ],
)
def test_invalid_event_fields(body):
    with pytest.raises(ValidationError):
        EventCreate.model_validate(body)


@pytest.mark.parametrize(
    "schema,body",
    [
        (EventPatch, {}),
        (EventPatch, {"title": None}),
        (EventPatch, {"description": None}),
        (JudgePatch, {"number": None}),
        (JudgePatch, {"credential": "secret"}),
        (EntryCreate, {"number": 1, "name": "entry"}),
        (EntryCreate, {"number": " ", "name": "entry"}),
    ],
)
def test_patch_and_number_validation(schema, body):
    with pytest.raises(ValidationError):
        schema.model_validate(body)


@pytest.mark.parametrize(
    "changes",
    [
        {"maximum": "NaN"},
        {"maximum": "Infinity"},
        {"maximum": "1e999999"},
        {"maximum": 100},
        {"maximum": "0"},
        {"step": "0"},
        {"step": "0.3"},
        {"weight": "0.9"},
        {"weight": "1.0000001"},
    ],
)
def test_invalid_rule_decimal_and_weight(changes):
    with pytest.raises(ValidationError):
        RuleInput(criteria=[{"criterion_id": "total", "name": "总分", **changes}])


def test_rule_validation_and_nullable_patch():
    rule = RuleInput(
        criteria=[{"criterion_id": "total", "name": "总分"}],
        algorithm="trimmed_mean",
        minimum_ballots=5,
    )
    assert rule.criteria[0].maximum == "100"
    with pytest.raises(ValidationError):
        RuleInput(**{**rule.model_dump(), "minimum_ballots": 4})
    with pytest.raises(ValidationError):
        RuleInput(**{**rule.model_dump(), "mode": "multi"})
    with pytest.raises(ValidationError):
        RuleInput(
            mode="multi",
            criteria=[
                {"criterion_id": "x", "name": "a", "weight": "0.5"},
                {"criterion_id": "x", "name": "b", "weight": "0.5"},
            ],
        )
    patch = EventPatch(planned_at=None, scoring_rule=None, duration_seconds=None)
    assert patch.model_dump(exclude_unset=True) == {
        "planned_at": None,
        "scoring_rule": None,
        "duration_seconds": None,
    }
    assert EntryCreate(number=" 001 ", name="对象").number == "001"


def test_all_event_routes_require_authentication_and_document_errors():
    app = create_app(Settings(_env_file=None))
    with TestClient(app) as client:
        paths = app.openapi()["paths"]
        operations = 0
        for path, methods in paths.items():
            if not path.startswith("/api/v1/events"):
                continue
            for method, spec in methods.items():
                operations += 1
                assert all(str(code) in spec["responses"] for code in (401, 403, 404, 409, 422))
                url = path.replace("{event_id}", "event").replace("{entry_id}", "entry")
                url = url.replace("{judge_id}", "judge")
                response = client.request(method, url, headers={"Origin": "http://localhost:5173"})
                assert response.status_code == 401
        assert operations == 15
