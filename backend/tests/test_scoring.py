from decimal import ROUND_DOWN, Decimal, Inexact, Rounded, localcontext
from itertools import permutations

import pytest

from score_api.scoring import (
    Algorithm,
    Ballot,
    Criterion,
    Exclusion,
    RankingEntry,
    ScoringError,
    ScoringRule,
    aggregate,
    default_minimum_ballots,
    personal_total,
    rank_results,
    validate_score,
)


def single_rule(n=5, algorithm=Algorithm.MEAN, k=None, maximum="100", step="0.1"):
    return ScoringRule((Criterion("score", maximum, step=step),), n, algorithm, k)


def ballots(*values):
    return tuple(Ballot(f"{index:02}", {"score": value}) for index, value in enumerate(values, 1))


def test_at05_weighted_personal_total():
    rule = ScoringRule(
        (
            Criterion("content", "100", "0.5"),
            Criterion("performance", "10", "0.3"),
            Criterion("innovation", "20", "0.2"),
        ),
        1,
    )
    scores = {"innovation": "18", "content": "90", "performance": "8"}
    assert personal_total(rule, scores) == Decimal("87")
    result = aggregate(rule, (Ballot("01", scores),))
    assert str(result.final_score) == "87.00"
    assert scores == {"innovation": "18", "content": "90", "performance": "8"}


@pytest.mark.parametrize("raw,expected", [("0", "0"), ("8", "40"), ("20", "100")])
def test_single_criterion_normalizes_to_percent(raw, expected):
    assert personal_total(single_rule(maximum="20"), {"score": raw}) == Decimal(expected)


def test_zero_is_valid_missing_is_not_and_trailing_zeroes_are_equivalent():
    criterion = Criterion("score")
    assert validate_score("0", criterion) == 0
    assert validate_score("90.000", criterion) == Decimal("90")
    result = aggregate(single_rule(1), ballots("0"))
    assert result.can_publish
    assert str(result.final_score) == "0.00"
    with pytest.raises(ScoringError):
        validate_score(None, criterion)


@pytest.mark.parametrize(
    "value", [None, "", "abc", "NaN", "sNaN", "Infinity", "-Infinity", 1.1, 0, True]
)
def test_reject_invalid_decimal_inputs(value):
    with pytest.raises(ScoringError):
        validate_score(value, Criterion("score"))


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity")])
def test_reject_nonfinite_decimal_objects(value):
    with pytest.raises(ScoringError):
        personal_total(single_rule(), {"score": value})


@pytest.mark.parametrize("value", ["-0.1", "100.1", "0.01", "99.99"])
def test_range_and_default_step(value):
    with pytest.raises(ScoringError):
        validate_score(value, Criterion("score"))


def test_arbitrary_decimal_step():
    criterion = Criterion("score", "10", step="0.25")
    assert validate_score("9.75", criterion) == Decimal("9.75")
    with pytest.raises(ScoringError):
        validate_score("9.8", criterion)


@pytest.mark.parametrize("scores", [{}, {"score": None}, {"other": "1"}, {"score": "1", "x": "2"}])
def test_all_and_only_configured_dimensions_required(scores):
    with pytest.raises(ScoringError):
        personal_total(single_rule(), scores)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"maximum": "0"},
        {"maximum": "-1"},
        {"maximum": "NaN"},
        {"maximum": 100.0},
        {"step": "0"},
        {"step": "-0.1"},
        {"step": "101"},
        {"step": "0.3"},
        {"step": "Infinity"},
        {"weight": "-0.1"},
        {"weight": "1.1"},
        {"weight": "NaN"},
    ],
)
def test_invalid_criterion_configuration(kwargs):
    with pytest.raises(ScoringError):
        Criterion("score", **kwargs)


@pytest.mark.parametrize(
    "criteria",
    [(), (Criterion("a", weight="0.9"),), (Criterion("a"), Criterion("a"))],
)
def test_invalid_criteria_collection(criteria):
    with pytest.raises(ScoringError):
        ScoringRule(criteria, 5)


def test_decimal_weights_sum_exactly_and_zero_weight_still_requires_a_score():
    rule = ScoringRule(
        (Criterion("a", weight="0.1"), Criterion("b", weight="0.9"), Criterion("c", weight="0")),
        1,
    )
    assert personal_total(rule, {"a": "100", "b": "100", "c": "0"}) == 100
    with pytest.raises(ScoringError):
        personal_total(rule, {"a": "100", "b": "100"})


@pytest.mark.parametrize(
    "n,algorithm,expected",
    [
        (1, Algorithm.MEAN, 1),
        (5, Algorithm.MEAN, 4),
        (6, Algorithm.MEAN, 5),
        (5, Algorithm.TRIMMED_MEAN, 5),
        (6, Algorithm.TRIMMED_MEAN, 5),
        (50, Algorithm.TRIMMED_MEAN, 40),
    ],
)
def test_default_k(n, algorithm, expected):
    assert default_minimum_ballots(n, algorithm) == expected
    assert single_rule(n, algorithm).minimum_ballots == expected


@pytest.mark.parametrize("n", [0, -1, 1.5, True, "5"])
def test_invalid_expected_count(n):
    with pytest.raises(ScoringError):
        single_rule(n)


@pytest.mark.parametrize("k", [0, -1, 6, True, 1.5, "4"])
def test_invalid_minimum_count(k):
    with pytest.raises(ScoringError):
        single_rule(k=k)


@pytest.mark.parametrize("n,k", [(4, None), (4, 4), (5, 4)])
def test_trimmed_mean_configuration_floor(n, k):
    with pytest.raises(ScoringError):
        single_rule(n, Algorithm.TRIMMED_MEAN, k)


def test_unknown_algorithm_rejected():
    with pytest.raises(ScoringError):
        single_rule(algorithm="median")


def test_at11_trimmed_mean_keeps_raw_ballots_and_marks_two_exclusions():
    original = ballots("80", "85", "90", "95", "100")
    result = aggregate(single_rule(algorithm=Algorithm.TRIMMED_MEAN), original)
    assert str(result.final_score) == "90.00"
    assert result.can_publish
    assert result.valid_count == result.expected_count == 5
    assert len(result.ballots) == 5
    assert [b.scores for b in result.ballots] == [
        (("score", Decimal(v)),) for v in (80, 85, 90, 95, 100)
    ]
    assert [b.exclusion for b in result.ballots] == [
        Exclusion.LOWEST,
        None,
        None,
        None,
        Exclusion.HIGHEST,
    ]
    assert original[0].scores == {"score": "80"}


def test_at12_four_ballots_do_not_fall_back_to_mean():
    result = aggregate(
        single_rule(algorithm=Algorithm.TRIMMED_MEAN), ballots("80", "85", "90", "95")
    )
    assert result.final_score is None
    assert not result.can_publish
    assert result.valid_count == 4
    assert all(b.exclusion is None for b in result.ballots)


def test_at13_actual_ballots_are_denominator_missing_judges_are_not_zeroes():
    result = aggregate(single_rule(k=4), ballots("80", "85", "90", "95"))
    assert str(result.final_score) == "87.50"
    assert (result.valid_count, result.expected_count, result.minimum_ballots) == (4, 5, 4)
    assert all(b.exclusion is None for b in result.ballots)


@pytest.mark.parametrize("values", [(), ("80", "90", "100")])
def test_mean_below_k_has_no_result(values):
    result = aggregate(single_rule(k=4), ballots(*values))
    assert result.final_score is None
    assert not result.can_publish


def test_duplicate_judges_and_excess_ballots_rejected():
    with pytest.raises(ScoringError):
        aggregate(single_rule(), (Ballot("01", {"score": "1"}), Ballot("01", {"score": "2"})))
    with pytest.raises(ScoringError):
        aggregate(single_rule(1), ballots("1", "2"))


@pytest.mark.parametrize("number", ["", "  ", 1, None])
def test_judge_numbers_are_nonempty_strings(number):
    with pytest.raises(ScoringError):
        aggregate(single_rule(1), (Ballot(number, {"score": "1"}),))


def test_all_equal_extremes_are_stable_for_every_input_order():
    rule = single_rule(algorithm=Algorithm.TRIMMED_MEAN)
    inputs = tuple(Ballot(number, {"score": "90"}) for number in ("01", "02", "10", "2", "9"))
    for permutation in permutations(inputs):
        result = aggregate(rule, permutation)
        assert result.final_score == Decimal("90.00")
        assert {b.judge_number: b.exclusion for b in result.ballots if b.exclusion} == {
            "01": Exclusion.LOWEST,
            "9": Exclusion.HIGHEST,
        }


def test_repeated_extremes_remove_only_one_each():
    result = aggregate(
        single_rule(algorithm=Algorithm.TRIMMED_MEAN), ballots("80", "80", "90", "100", "100")
    )
    assert [b.judge_number for b in result.ballots if b.exclusion] == ["01", "05"]
    assert result.final_score == Decimal("90.00")


def test_trim_whole_totals_not_individual_dimensions():
    rule = ScoringRule(
        (Criterion("a", weight="0.5"), Criterion("b", weight="0.5")),
        5,
        Algorithm.TRIMMED_MEAN,
    )
    result = aggregate(
        rule,
        tuple(
            Ballot(str(i), {"a": a, "b": b})
            for i, (a, b) in enumerate(
                (("0", "100"), ("100", "0"), ("40", "40"), ("60", "60"), ("80", "80"))
            )
        ),
    )
    assert str(result.final_score) == "53.33"
    assert {b.judge_number for b in result.ballots if b.exclusion} == {"2", "4"}


def test_trim_uses_unrounded_totals_before_judge_number():
    result = aggregate(
        single_rule(algorithm=Algorithm.TRIMMED_MEAN, step="0.001"),
        ballots("90.004", "90.001", "90.003", "90.002", "90.000"),
    )
    assert {b.judge_number: b.exclusion for b in result.ballots if b.exclusion} == {
        "05": Exclusion.LOWEST,
        "01": Exclusion.HIGHEST,
    }


def test_dimension_contributions_are_not_rounded():
    rule = ScoringRule((Criterion("a", "3", "0.5"), Criterion("b", "3", "0.5")), 1)
    result = aggregate(rule, (Ballot("01", {"a": "1", "b": "1"}),))
    assert str(result.final_score) == "33.33"  # Rounding contributions would produce 33.34.


def test_personal_totals_are_not_rounded_before_aggregation():
    result = aggregate(single_rule(2, step="0.001"), ballots("1.004", "1.005"))
    assert str(result.final_score) == "1.00"  # Rounded personal totals would produce 1.01.
    assert [b.total for b in result.ballots] == [Decimal("1.004"), Decimal("1.005")]


def test_recurring_contributions_at_exact_half_cent_round_up():
    rule = ScoringRule(
        tuple(Criterion(key, "3", "0.00005") for key in ("a", "b", "c"))
        + (Criterion("rest", weight="0.99985"),),
        1,
    )
    scores = {"a": "1", "b": "1", "c": "1", "rest": "0"}
    assert personal_total(rule, scores) == Decimal("0.005")
    assert str(aggregate(rule, (Ballot("01", scores),)).final_score) == "0.01"


def test_mathematically_equal_recurring_totals_trim_by_judge_number():
    rule = ScoringRule(
        tuple(Criterion(key, "3", "0.25") for key in ("a", "b", "c"))
        + (Criterion("rest", weight="0.25"),),
        5,
        Algorithm.TRIMMED_MEAN,
    )
    inputs = (
        Ballot("01", {"a": "0.1", "b": "0.1", "c": "0.1", "rest": "0"}),
        Ballot("02", {"a": "0.3", "b": "0", "c": "0", "rest": "0"}),
        Ballot("03", {"a": "0", "b": "0.3", "c": "0", "rest": "0"}),
        Ballot("04", {"a": "0", "b": "0", "c": "0.3", "rest": "0"}),
        Ballot("05", {"a": "0.1", "b": "0.1", "c": "0.1", "rest": "0"}),
    )
    result = aggregate(rule, inputs)
    assert {b.judge_number: b.exclusion for b in result.ballots if b.exclusion} == {
        "01": Exclusion.LOWEST,
        "05": Exclusion.HIGHEST,
    }


@pytest.mark.parametrize("raw,expected", [("1.005", "1.01"), ("1.004", "1.00"), ("0.005", "0.01")])
def test_final_round_half_up(raw, expected):
    assert str(aggregate(single_rule(1, step="0.001"), ballots(raw)).final_score) == expected


def test_at16_published_scores_competition_rank_and_display_order():
    result = rank_results(
        (
            RankingEntry("third", "90.00", 30, True),
            RankingEntry("first", "95.00", 10, True),
            RankingEntry("second", "90.00", 20, True),
            RankingEntry("fourth", "85.00", 40, True),
            RankingEntry("unpublished", "100.00", 0),
            RankingEntry("skipped", None, 50),
            RankingEntry("no-result", None, 60, True),
            RankingEntry("zero", "0.00", 70, True),
        )
    )
    assert [(r.entry_id, r.rank) for r in result] == [
        ("first", 1),
        ("second", 2),
        ("third", 2),
        ("fourth", 4),
        ("zero", 5),
    ]


def test_different_raw_totals_with_same_published_score_are_tied():
    rule = single_rule(1, step="0.001")
    scores = [aggregate(rule, ballots(value)).final_score for value in ("90.001", "90.004")]
    assert [
        r.rank
        for r in rank_results(
            tuple(RankingEntry(str(i), score, i, True) for i, score in enumerate(scores))
        )
    ] == [1, 1]
    assert rank_results(()) == ()


@pytest.mark.parametrize("score", ["90.001", "NaN", "Infinity", "-0.01", "100.01", 90.0])
def test_ranking_rejects_invalid_or_unrounded_final_scores(score):
    with pytest.raises(ScoringError):
        rank_results((RankingEntry("a", score, 1, True),))


def test_ranking_rejects_duplicate_objects():
    with pytest.raises(ScoringError):
        rank_results((RankingEntry("a", "90", 1, True), RankingEntry("a", "90", 2, True)))


def test_scoring_is_independent_of_ambient_decimal_context():
    with localcontext() as ambient:
        ambient.prec = 2
        ambient.rounding = ROUND_DOWN
        ambient.traps[Inexact] = True
        ambient.traps[Rounded] = True
        rule = single_rule(1, maximum="3")
        assert str(aggregate(rule, ballots("1")).final_score) == "33.33"
        assert personal_total(rule, {"score": "1"}).as_tuple().exponent < -40
        result = rank_results(
            (RankingEntry("a", "99.99", 1, True), RankingEntry("b", "99.98", 0, True))
        )
        assert [r.entry_id for r in result] == ["a", "b"]
        assert ambient.prec == 2 and ambient.rounding == ROUND_DOWN
