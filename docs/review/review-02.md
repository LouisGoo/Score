# Review 02：十进制评分核心

建议提交：`feat(scoring): 实现十进制评分规则`

状态：实现、自查及本地验证完成，等待用户 review；本批改动尚未提交或 push。
基于 commit1 `1e481a2` 开发。本批无新增依赖、数据库迁移或 HTTP 端点。

## 文件入口与范围

- [scoring.py](../backend/src/score_api/scoring.py)：规则配置、输入校验、个人百分制总分、最低份数、平均/去极值汇总、公布成绩排名。
- [test_scoring.py](../backend/tests/test_scoring.py)：需求示例与数值/非法输入/稳定性回归测试。
- [README](../README.md)、[提交计划](commit-plan.md)、[接口文档](api.md)：同步交付状态及调用入口。

## 调用示例

安装项目后，在 Python 中调用：

```python
from score_api.scoring import (
    Ballot, Criterion, RankingEntry, ScoringRule, aggregate, rank_results,
)

rule = ScoringRule(
    criteria=(
        Criterion("content", maximum="100", weight="0.5"),
        Criterion("performance", maximum="10", weight="0.3"),
        Criterion("innovation", maximum="20", weight="0.2"),
    ),
    expected_count=1,
)
result = aggregate(rule, (
    Ballot("01", {"content": "90", "performance": "8", "innovation": "18"}),
))
assert str(result.final_score) == "87.00"
assert result.can_publish
ranking = rank_results((RankingEntry("entry-01", result.final_score, 1, published=True),))
assert ranking[0].rank == 1
```

## 数值与集成约定

- 分数、满分、权重与步长只接受十进制字符串或有限 `Decimal`；拒绝 float、int、bool、空值、NaN/sNaN/Infinity。零分是有效分，尾随零不改变步长合规性。
- `Criterion` 默认满分 100、权重 1、步长 0.1。满分和步长为正数，满分须能被步长整除；分数在闭区间 `[0, maximum]` 内且为步长整数倍。允许零权重维度，但仍需填写；所有权重须精确合计为 1。
- 维度 ID 非空且唯一，每份评分须恰好包含所有配置维度。非法规则或评分抛出 `ScoringError(ValueError)`；这不是尚未实现的 HTTP 错误包装。
- 平均分默认 `K=max(1, ceil(0.8N))`；去极值默认 `K=max(5, ceil(0.8N))`。自定义 K 仍须满足算法最低人数及 `K<=N`；去极值不允许配置不足 5 位评委，不自动降级。
- `aggregate` 接收每位评委的一个当前有效版本；重复评委编号或有效份数超过 N 会报错。缺交评委不传入、不补零；结果包含 `valid_count`、`expected_count`、`minimum_ballots`，去极值后有效份数仍为原始提交份数。
- `n<K` 返回完整个人评分及 `final_score=None`，不作剔除；`can_publish` 仅表示数值门槛已满足。身份/名单归属、任务状态、提前收评原因、评分版本、冻结快照及公布权限由后续业务层实现。
- 内部全部使用 Decimal，独立运算上下文至少 50 位有效数字，随输入长度、维度数量和累加份数增加；不受调用方 Decimal 精度、舍入模式和异常陷阱影响。维度贡献先通分并累加，避免循环小数的中间除法影响精确同分与半分边界；最终汇总从原始维度分计算，不使用展示用个人总分。
- 个人总分不量化到两位小数；不能有限表示的比值保持高精度 Decimal。去极值按同分母的精确总分分子、评委编号排序，数值上等价于按未舍入总分排序；只剔除首尾各一份不同评委的完整评分，并保留 `lowest` / `highest` 标记及全部原始分。
- 评委编号按字符串字典序比较，保留前导零，不转换为整数，例如 `"01" < "10" < "2"`。返回的评分明细维持传入顺序，标记不受该顺序影响。
- 最终汇总统一 `ROUND_HALF_UP` 至两位小数。排名仅接收已按两位小数确定的成绩；`published=False` 或 `final_score=None` 的对象不参与排名。相同公布分并列，采用 1、2、2、4；同分按 `display_order`，展示顺序也相同时保留传入顺序。
- HTTP 请求长度/规则规模限制和持久化 DECIMAL 字段上限随后续接口与数据库实现确定；本批不提前声明数据库存储精度。

## 验收证据

日期：2026-10-10。环境：Ubuntu 22.04 / Python 3.10.12 / Node 24.21.0，沿用仓库 `.venv` 和现有锁文件。

| 检查 | 命令与结果 |
| --- | --- |
| 后端 lint | `cd backend && ../.venv/bin/ruff check .`：通过 |
| 后端格式 | `cd backend && ../.venv/bin/ruff format --check .`：6 个文件通过 |
| 后端测试 | `cd backend && ../.venv/bin/pytest -q`：96 passed（95 项评分用例 + 1 项已有存活检查） |
| 前端类型检查/构建 | `cd frontend && npm run build`：通过 |
| 补丁空白检查 | `git diff --check`：通过 |

| 验收项 | 自动化证据与范围 |
| --- | --- |
| AT-05 | 多维度输入 90、8、18 得到 87.00 |
| AT-11 | 80、85、90、95、100 去极值得到 90.00，保留全部原始分与两份标记 |
| AT-12 | 去极值只收到 4 份时无最终成绩，不回退平均分；收评/补评状态流转留待后续提交 |
| AT-13 | N=5、K=4 时按四份平均得到 87.50，保留有效 4/应交 5；原因记录留待后续提交 |
| AT-16 | 按公布的两位小数成绩并列排名 1、2、2、4，排除未公布/无结果/跳过 |
| 数值边界 | 范围/步长/缺失/额外维度、零分、非法数值、权重及 K 配置、ROUND_HALF_UP、循环小数半分边界 |
| 去极值稳定性 | 五份同分的全部 120 种传入排列、重复极值、未舍入排序、完整总分剔除及精确同分 |
| 不提前舍入 | 维度先舍入会得到 33.34 的例子实际为 33.33；个人先舍入会得到 1.01 的例子实际为 1.00 |
| 上下文隔离 | 调用方精度降至 2、ROUND_DOWN、启用 Inexact/Rounded 陷阱，仍正确计算且不改调用方上下文 |

以上为纯函数验收，未将 AT-12/13 的业务流程宣称为完整通过。GitHub Actions 尚未在远程执行。

## Review 重点

1. 数值实现只在最终成绩量化；精确通分和原始分复算避免中间除法误差及已舍入个人分影响汇总。
2. 编号字符串排序、规则满分可达、权重单位以及不足 K 返回空成绩的约定，能否直接供后续业务层复用。
3. 汇总保留原始维度分/有效人数/剔除标记；排名以公布分和展示顺序为准。

下一批为 03：MySQL 持久化基础；本次不提前实现。
