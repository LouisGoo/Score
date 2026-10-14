from types import SimpleNamespace

import pytest

from score_api.core.errors import APIError
from score_api.events.publication import inspect_publication, validate_publication


def inspect(rule, count=1, entries=True):
    return inspect_publication(
        SimpleNamespace(scoring_rule=rule),
        [object()] if entries else [],
        [SimpleNamespace(credential_is_set=False) for _ in range(count)],
    )


def rule(**changes):
    return {"criteria": [{"criterion_id": "total", "name": "总分"}], **changes}


@pytest.mark.parametrize(
    "count,algorithm,minimum,expected",
    [
        (1, "mean", None, 1),
        (6, "mean", None, 5),
        (6, "trimmed_mean", None, 5),
        (7, "trimmed_mean", None, 6),
        (6, "mean", 2, 2),
        (5, "trimmed_mean", 5, 5),
    ],
)
def test_check_uses_scoring_threshold(count, algorithm, minimum, expected):
    check, frozen = inspect(rule(algorithm=algorithm, minimum_ballots=minimum), count)
    assert check.can_publish and check.issues == []
    assert check.minimum_ballots == frozen["minimum_ballots"] == expected
    assert frozen["expected_count"] == check.judge_count == count
    assert check.missing_credential_count == count


@pytest.mark.parametrize(
    "config,count,code,field",
    [
        (rule(algorithm="trimmed_mean"), 4, "TRIMMED_MEAN_JUDGES_REQUIRED", "algorithm"),
        (rule(minimum_ballots=2), 1, "MINIMUM_BALLOTS_EXCEEDS_JUDGES", "minimum_ballots"),
        (
            rule(algorithm="trimmed_mean", minimum_ballots=4),
            5,
            "MINIMUM_BALLOTS_BELOW_FLOOR",
            "minimum_ballots",
        ),
        (
            rule(criteria=[{"criterion_id": "a", "name": "a", "weight": "0.9"}]),
            1,
            "WEIGHTS_SUM_INVALID",
            "criteria",
        ),
        (
            rule(criteria=[{"criterion_id": "a", "name": "a", "step": "SECRET"}]),
            1,
            "RULE_INVALID",
            "criteria.0.step",
        ),
        (rule(mode="multi"), 1, "RULE_INVALID", ""),
    ],
)
def test_rule_issues_are_located_and_shared_with_publish(config, count, code, field):
    check, frozen = inspect(config, count)
    assert not check.can_publish and frozen is None and check.minimum_ballots is None
    assert check.issues[0].code == code
    assert check.issues[0].field == "scoring_rule" + (f".{field}" if field else "")
    assert "SECRET" not in check.model_dump_json()
    with pytest.raises(APIError) as exc:
        validate_publication(
            SimpleNamespace(scoring_rule=config),
            [object()],
            [SimpleNamespace(credential_is_set=False) for _ in range(count)],
        )
    assert exc.value.code == "PUBLISH_INVALID" and exc.value.issues == check.issues


def test_collects_missing_requirements_and_does_not_invent_threshold():
    check, frozen = inspect(None, count=0, entries=False)
    assert [issue.code for issue in check.issues] == [
        "ENTRIES_REQUIRED",
        "JUDGES_REQUIRED",
        "SCORING_RULE_REQUIRED",
    ]
    assert check.minimum_ballots is None and frozen is None
    check, _ = inspect(rule(), count=0)
    assert [issue.code for issue in check.issues] == ["JUDGES_REQUIRED"]
    assert check.minimum_ballots is None
