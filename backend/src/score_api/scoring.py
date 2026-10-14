"""评分纯函数，不依赖 HTTP、持久化、时钟或调用方的 Decimal 运算上下文。

权重使用合计为 1 的小数。评委编号保留前导零，按字符串字典序比较，
用于确定同分时的去极值顺序。只有最终成绩舍入到两位小数，个人总分保留高精度。
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext
from enum import Enum
from math import prod

DecimalInput = Decimal | str
CENT = Decimal("0.01")
HUNDRED = Decimal("100")


class ScoringError(ValueError):
    """评分配置或输入不合法；独立于后续 HTTP 层的错误响应。"""

    def __init__(self, message: str, *, code: str = "RULE_INVALID", field: str = ""):
        super().__init__(message)
        self.code, self.field = code, field


class Algorithm(str, Enum):
    MEAN = "mean"
    TRIMMED_MEAN = "trimmed_mean"


def _decimal(value: DecimalInput, name: str) -> Decimal:
    # 只接受字符串或 Decimal，避免引入浮点误差或将空值、布尔值当作分数。
    if not isinstance(value, (str, Decimal)):
        raise ScoringError(f"{name} must be a decimal string or Decimal")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ScoringError(f"{name} must be a decimal number") from exc
    if not result.is_finite():
        raise ScoringError(f"{name} must be finite")
    return result


def _identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ScoringError(f"{name} must be a nonempty string")


def _positive_integer(value: int, name: str) -> None:
    if type(value) is not int or value < 1:
        raise ScoringError(f"{name} must be a positive integer")


def _context(values: Sequence[Decimal], count: int = 1, factors: int = 4) -> Context:
    # 根据输入位数、连乘因子和累加项数预留精度，至少保留 50 位有效数字。
    # 新建上下文，隔离调用方的舍入模式和数值异常触发设置。
    width = max(
        (len(v.as_tuple().digits) + abs(v.as_tuple().exponent) for v in values),
        default=1,
    )
    return Context(prec=max(50, factors * width + len(str(count)) + 20), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Criterion:
    """单个评分维度：标识、满分、权重和输入步长。"""

    criterion_id: str
    maximum: DecimalInput = Decimal("100")
    weight: DecimalInput = Decimal("1")
    step: DecimalInput = Decimal("0.1")

    def __post_init__(self) -> None:
        _identifier(self.criterion_id, "criterion_id")
        # 冻结对象仅在初始化时统一转换数值类型，之后禁止直接修改字段。
        for name in ("maximum", "weight", "step"):
            object.__setattr__(self, name, _decimal(getattr(self, name), name))
        if self.maximum <= 0 or self.step <= 0 or self.step > self.maximum:
            raise ScoringError("maximum and step must be positive, with step <= maximum")
        if not 0 <= self.weight <= 1:
            raise ScoringError("weight must be between 0 and 1")
        with localcontext(_context((self.maximum, self.step))):
            if self.maximum % self.step != 0:
                raise ScoringError("maximum must be a multiple of step")


def default_minimum_ballots(expected_count: int, algorithm: Algorithm = Algorithm.MEAN) -> int:
    """将应交份数的 80% 向上取整，再应用算法最低人数要求；拒绝无法满足的规则。"""
    _positive_integer(expected_count, "expected_count")
    try:
        algorithm = Algorithm(algorithm)
    except (ValueError, TypeError) as exc:
        raise ScoringError("unknown aggregation algorithm") from exc
    minimum = max(5 if algorithm == Algorithm.TRIMMED_MEAN else 1, (4 * expected_count + 4) // 5)
    if minimum > expected_count:
        raise ScoringError(
            "trimmed mean requires at least five expected judges",
            code="TRIMMED_MEAN_JUDGES_REQUIRED",
            field="algorithm",
        )
    return minimum


@dataclass(frozen=True)
class ScoringRule:
    """完整评分规则：维度、应交份数 N、汇总算法和最低有效份数 K。"""

    criteria: tuple[Criterion, ...]
    expected_count: int
    algorithm: Algorithm = Algorithm.MEAN
    minimum_ballots: int | None = None

    def __post_init__(self) -> None:
        criteria = tuple(self.criteria)
        if not criteria or any(not isinstance(item, Criterion) for item in criteria):
            raise ScoringError("at least one Criterion is required")
        if len({item.criterion_id for item in criteria}) != len(criteria):
            raise ScoringError("criterion IDs must be unique")
        with localcontext(_context(tuple(item.weight for item in criteria), len(criteria))):
            if sum((item.weight for item in criteria), Decimal(0)) != 1:
                raise ScoringError(
                    "weights must sum exactly to 1", code="WEIGHTS_SUM_INVALID", field="criteria"
                )
        default = default_minimum_ballots(self.expected_count, self.algorithm)
        minimum = default if self.minimum_ballots is None else self.minimum_ballots
        _positive_integer(minimum, "minimum_ballots")
        algorithm = Algorithm(self.algorithm)
        floor = 5 if algorithm == Algorithm.TRIMMED_MEAN else 1
        if minimum < floor:
            raise ScoringError(
                "minimum_ballots must meet the algorithm floor",
                code="MINIMUM_BALLOTS_BELOW_FLOOR",
                field="minimum_ballots",
            )
        if minimum > self.expected_count:
            raise ScoringError(
                "minimum_ballots must not exceed N",
                code="MINIMUM_BALLOTS_EXCEEDS_JUDGES",
                field="minimum_ballots",
            )
        object.__setattr__(self, "criteria", criteria)
        object.__setattr__(self, "algorithm", algorithm)
        object.__setattr__(self, "minimum_ballots", minimum)


def validate_score(value: DecimalInput, criterion: Criterion) -> Decimal:
    """校验范围及步长；零分有效，空值无效，步长从零起算。"""
    score = _decimal(value, f"score[{criterion.criterion_id}]")
    if not 0 <= score <= criterion.maximum:
        raise ScoringError(f"score[{criterion.criterion_id}] is outside its range")
    with localcontext(_context((score, criterion.step))):
        if score % criterion.step != 0:
            raise ScoringError(f"score[{criterion.criterion_id}] does not match its step")
    return score


def _validated_scores(
    rule: ScoringRule, scores: Mapping[str, DecimalInput]
) -> tuple[tuple[str, Decimal], ...]:
    """要求维度完整且无多余项，按规则中的维度顺序返回校验后的分数。"""
    if not isinstance(scores, Mapping) or set(scores) != {c.criterion_id for c in rule.criteria}:
        raise ScoringError("scores must contain exactly the configured criteria")
    return tuple((c.criterion_id, validate_score(scores[c.criterion_id], c)) for c in rule.criteria)


def _normalization(rule: ScoringRule) -> tuple[Decimal, tuple[Decimal, ...]]:
    # 先通分，将加法和大小比较放在除法之前，避免循环小数影响同分和半分边界。
    # 公共分母 D 为各维度满分之积；第 i 项系数为 100 × 权重 × 其余维度满分之积。
    maxima = tuple(c.maximum for c in rule.criteria)
    denominator = prod(maxima, start=Decimal(1))
    coefficients = tuple(
        HUNDRED * c.weight * prod(maxima[:i] + maxima[i + 1 :], start=Decimal(1))
        for i, c in enumerate(rule.criteria)
    )
    return denominator, coefficients


def _numerator(
    coefficients: tuple[Decimal, ...], scores: tuple[tuple[str, Decimal], ...]
) -> Decimal:
    """累加各维度的原始分乘以通分系数，得到个人百分制总分的分子。"""
    return sum(
        (value * coefficient for coefficient, (_, value) in zip(coefficients, scores, strict=True)),
        Decimal(0),
    )


def _rule_values(rule: ScoringRule) -> tuple[Decimal, ...]:
    return tuple(v for c in rule.criteria for v in (c.maximum, c.weight, c.step))


def personal_total(rule: ScoringRule, scores: Mapping[str, DecimalInput]) -> Decimal:
    """归一化到百分制；不将维度贡献或个人总分提前量化到两位小数。"""
    validated = _validated_scores(rule, scores)
    with localcontext(
        _context(
            _rule_values(rule) + tuple(v for _, v in validated),
            len(rule.criteria),
            4 * (len(rule.criteria) + 2),
        )
    ):
        denominator, coefficients = _normalization(rule)
        return _numerator(coefficients, validated) / denominator


@dataclass(frozen=True)
class Ballot:
    """一位评委的当前有效评分，包含编号和各维度原始分。"""

    judge_number: str
    scores: Mapping[str, DecimalInput]


class Exclusion(str, Enum):
    """去极值标记：作为最低分或最高分剔除。"""

    LOWEST = "lowest"
    HIGHEST = "highest"


@dataclass(frozen=True)
class EvaluatedBallot:
    """计算后的评分明细，保留原始分、个人总分及可选的剔除标记。"""

    judge_number: str
    scores: tuple[tuple[str, Decimal], ...]
    total: Decimal
    exclusion: Exclusion | None = None


@dataclass(frozen=True)
class AggregationResult:
    """汇总结果；有效份数包含被去极值的评分，不足 K 时最终成绩为空。"""

    final_score: Decimal | None
    valid_count: int
    expected_count: int
    minimum_ballots: int
    ballots: tuple[EvaluatedBallot, ...]

    @property
    def can_publish(self) -> bool:
        """仅表示达到数值门槛；任务状态与公布权限仍由调用方校验。"""
        return self.final_score is not None


def aggregate(rule: ScoringRule, ballots: Sequence[Ballot]) -> AggregationResult:
    """汇总每位评委的一份当前有效评分，保留原始分和去极值标记。

    缺交评委不计入，不补零。有效份数不足 K 时，不生成最终成绩，也不剔除评分；
    调用方仍可执行收评，收评状态流转不由本函数负责。
    """
    ballots = tuple(ballots)
    if len(ballots) > rule.expected_count:
        raise ScoringError("ballot count exceeds expected_count")
    seen = set()
    validated = []
    for ballot in ballots:
        _identifier(ballot.judge_number, "judge_number")
        if ballot.judge_number in seen:
            raise ScoringError("only one current ballot per judge is allowed")
        seen.add(ballot.judge_number)
        validated.append(_validated_scores(rule, ballot.scores))
    values = _rule_values(rule) + tuple(v for scores in validated for _, v in scores)
    with localcontext(
        _context(values, len(ballots) * len(rule.criteria), 4 * (len(rule.criteria) + 2))
    ):
        denominator, coefficients = _normalization(rule)
        numerators = tuple(_numerator(coefficients, scores) for scores in validated)
        evaluated = tuple(
            EvaluatedBallot(b.judge_number, scores, numerator / denominator)
            for b, scores, numerator in zip(ballots, validated, numerators, strict=True)
        )
        final_score = None
        if len(evaluated) >= rule.minimum_ballots:
            if rule.algorithm == Algorithm.TRIMMED_MEAN:
                # 所有分数共用正分母，比较分子即可精确排序；同分时按评委编号排序。
                ordered = sorted(
                    zip(evaluated, numerators, strict=True),
                    key=lambda pair: (pair[1], pair[0].judge_number),
                )
                exclusions = {
                    ordered[0][0].judge_number: Exclusion.LOWEST,
                    ordered[-1][0].judge_number: Exclusion.HIGHEST,
                }
                # 冻结数据通过 replace 生成新对象，保留所有评分及原始传入顺序。
                evaluated = tuple(
                    replace(b, exclusion=exclusions.get(b.judge_number)) for b in evaluated
                )
            retained = [
                numerator
                for b, numerator in zip(evaluated, numerators, strict=True)
                if b.exclusion is None
            ]
            # 按实际保留的份数求均分，仅在最终成绩处按 ROUND_HALF_UP 保留两位小数。
            final_score = (sum(retained, Decimal(0)) / (denominator * len(retained))).quantize(CENT)
        return AggregationResult(
            final_score, len(evaluated), rule.expected_count, rule.minimum_ballots, evaluated
        )


@dataclass(frozen=True)
class RankingEntry:
    """待排名对象：最终成绩、展示顺序和是否已公布。"""

    entry_id: str
    final_score: DecimalInput | None
    display_order: int
    published: bool = False


@dataclass(frozen=True)
class RankedEntry:
    """排名输出：对象标识、公布成绩和名次。"""

    entry_id: str
    final_score: Decimal
    rank: int


def rank_results(entries: Sequence[RankingEntry]) -> tuple[RankedEntry, ...]:
    """仅按已公布的两位小数成绩排名，同分采用 1、2、2、4 的并列名次。

    跳过或无结果的对象以 final_score=None 表示，不参与排名；未公布对象同样排除。
    同分按 display_order 排列；展示顺序也相同时，保留传入顺序。
    """
    included = []
    seen = set()
    for entry in entries:
        _identifier(entry.entry_id, "entry_id")
        if entry.entry_id in seen:
            raise ScoringError("ranking entry IDs must be unique")
        seen.add(entry.entry_id)
        if type(entry.published) is not bool or type(entry.display_order) is not int:
            raise ScoringError("published must be boolean and display_order must be integer")
        if not entry.published or entry.final_score is None:
            continue
        score = _decimal(entry.final_score, "final_score")
        with localcontext(_context((score,))):
            if not 0 <= score <= 100 or score % CENT != 0:
                raise ScoringError("ranking requires a final score in 0..100 rounded to cents")
            included.append((entry, score.quantize(CENT)))
    # 两次稳定排序让分数优先、展示顺序次之；避免用负号取反触发调用方的 Decimal 上下文。
    included.sort(key=lambda item: item[0].display_order)
    included.sort(key=lambda item: item[1], reverse=True)
    ranked = []
    previous = None
    rank = 0
    for position, (entry, score) in enumerate(included, start=1):
        # 同分沿用上一名次；分数变化时取实际位置，因此并列第二之后是第四名。
        if score != previous:
            rank = position
        ranked.append(RankedEntry(entry.entry_id, score, rank))
        previous = score
    return tuple(ranked)
