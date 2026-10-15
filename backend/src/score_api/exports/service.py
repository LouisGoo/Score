"""CSV 在同一无锁读视图内生成；冻结分数来自 ResultSnapshot，不重新聚合。"""

import csv
import io
import json
import re

from sqlalchemy import select

from score_api.ballots.models import Ballot, BallotAudit, BallotRevision
from score_api.events.models import EventAudit, EventSnapshot
from score_api.events.service import owned_event
from score_api.results.service import scoring_rule
from score_api.scoring import personal_total
from score_api.snapshots.service import public_data, require_published

COMMON = ["活动ID", "活动", "活动版本", "导出时间", "规则版本"]
ROUND = ["任务ID", "对象编号", "对象名称", "结果状态", "公布状态"]
RESULT = [
    "结果快照ID",
    "收评任务版本",
    "收评时间",
    "快照状态",
    "算法",
    "有效份数",
    "应交份数",
    "最低份数",
    "最终分",
    "名次",
]
SUMMARY = COMMON + ROUND + RESULT + ["缺交评委编号", "收评原因"]
DETAILS = (
    COMMON
    + ROUND
    + RESULT
    + [
        "评委编号",
        "评委名称",
        "评分单ID",
        "回执ID",
        "评分版本",
        "当前有效版本",
        "快照采用版本",
        "维度ID",
        "维度名称",
        "原始分",
        "个人总分",
        "提交时间",
        "计入标记",
        "剔除原因",
    ]
)
AUDIT = (
    COMMON
    + ROUND
    + [
        "审计ID",
        "操作时间",
        "操作者类型",
        "操作者ID",
        "操作",
        "目标ID",
        "原因",
        "变更前",
        "变更后",
        "请求ID",
    ]
)


def safe_cell(value):
    text = "" if value is None else str(value)
    # 引号本身不能阻止 Excel 执行公式；同时覆盖前导空白/控制字符与全角触发符。
    probe = re.sub(r"^[\s\x00-\x1f\ufeff]+", "", text)
    if text.startswith(("\t", "\r", "\n")) or probe.startswith(tuple("=+-@＝＋－＠")):
        return "'" + text
    return text


def csv_bytes(headers, rows):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow(safe_cell(row.get(column)) for column in headers)
    return output.getvalue().encode("utf-8-sig")


def timestamp(value):
    return value.isoformat() if value is not None else ""


def result_fields(result, row, ranks):
    if result is None:
        return {"快照状态": "尚未收评"}
    calc = result.calculation
    return {
        "结果快照ID": result.id,
        "收评任务版本": result.round_version,
        "收评时间": timestamp(result.closed_at),
        "快照状态": "历史收评（已重开）" if row.status in {"OPEN", "PAUSED"} else "最新收评",
        "算法": calc["algorithm"],
        "有效份数": calc["valid_count"],
        "应交份数": calc["expected_count"],
        "最低份数": calc["minimum_ballots"],
        "最终分": calc["final_score"],
        "名次": ranks.get(row.entry_id),
    }


def round_fields(row):
    return {
        "任务ID": row.id,
        "对象编号": row.number,
        "对象名称": row.name,
        "结果状态": row.status,
        "公布状态": "已公布" if row.status == "PUBLISHED" else "未公布",
    }


def detail_rows(session, event_id, selected, latest, judges, rule, bases):
    grouped = {}
    for ballot, revision in session.execute(
        select(Ballot, BallotRevision)
        .join(BallotRevision, BallotRevision.ballot_id == Ballot.id)
        .where(Ballot.event_id == event_id, BallotRevision.event_id == event_id)
        .order_by(Ballot.judge_id, BallotRevision.revision)
    ):
        grouped.setdefault(ballot.round_id, []).append((ballot, revision))
    criteria = {c["criterion_id"]: c["name"] for c in rule["criteria"]}
    parsed_rule = scoring_rule(rule)
    for row in selected:
        result = latest.get(row.id)
        frozen = {b["receipt_id"]: b for b in result.calculation["ballots"]} if result else {}
        frozen_versions = {b["judge_id"]: b["revision"] for b in frozen.values()}
        records = grouped.get(row.id, [])
        for ballot, revision in records:
            chosen = frozen.get(revision.id)
            judge = judges[ballot.judge_id]
            # 采用版本的原始分/总分/剔除标记直接来自冻结快照；历史版本以原始分复算。
            scores = chosen["scores"] if chosen else revision.scores
            total = (
                chosen["total"]
                if chosen
                else str(
                    personal_total(parsed_rule, {s["criterion_id"]: s["value"] for s in scores})
                )
            )
            for score in scores:
                yield {
                    **bases[row.id],
                    "评委编号": judge["number"],
                    "评委名称": judge["name"],
                    "评分单ID": ballot.id,
                    "回执ID": revision.id,
                    "评分版本": revision.revision,
                    "当前有效版本": ballot.current_revision,
                    "快照采用版本": frozen_versions.get(ballot.judge_id),
                    "维度ID": score["criterion_id"],
                    "维度名称": criteria[score["criterion_id"]],
                    "原始分": score["value"],
                    "个人总分": total,
                    "提交时间": timestamp(revision.accepted_at),
                    "计入标记": (
                        ("剔除" if chosen["exclusion"] else "计入")
                        if chosen
                        else ("未收评" if result is None else "非快照采用版本")
                    ),
                    "剔除原因": chosen["exclusion"] if chosen else None,
                }
        missing = (
            result.calculation["missing_judge_ids"]
            if result
            else judges.keys() - {b.judge_id for b, _ in records}
        )
        for judge_id in sorted(missing, key=lambda id_: judges[id_]["number"]):
            judge = judges[judge_id]
            yield {
                **bases[row.id],
                "评委编号": judge["number"],
                "评委名称": judge["name"],
                "计入标记": "缺交（收评时）" if result else "缺交（当前）",
            }


def audit_state(value):
    # 显式白名单，不序列化原始 before/after，避免未来新增敏感字段自动进入导出。
    allowed = {
        "status",
        "version",
        "credential_version",
        "credential_source",
        "credential_is_set",
        "credential_updated_at",
        "before_revision",
        "after_revision",
    }
    return json.dumps(
        {
            k: v
            for k, v in (value or {}).items()
            if k in allowed and isinstance(v, (str, int, bool))
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def audit_rows(session, event_id, common, rounds, selected):
    all_rounds = {r.id: r for r in rounds}
    allowed = {r.id for r in selected}
    records = []
    for audit in session.scalars(select(EventAudit).where(EventAudit.event_id == event_id)):
        row = all_rounds.get(audit.target_id)
        if row is not None and row.id not in allowed:
            continue
        records.append(
            {
                **common,
                **(round_fields(row) if row else {"公布状态": "活动级操作"}),
                "审计ID": audit.id,
                "操作时间": timestamp(audit.created_at),
                "操作者类型": "主办方" if audit.actor_id else "系统",
                "操作者ID": audit.actor_id,
                "操作": audit.action,
                "目标ID": audit.target_id,
                "原因": (audit.after or {}).get("reason"),
                "变更前": audit_state(audit.before),
                "变更后": audit_state(audit.after),
                "请求ID": audit.request_id,
            }
        )
    for audit, ballot in session.execute(
        select(BallotAudit, Ballot)
        .join(Ballot, Ballot.id == BallotAudit.ballot_id)
        .where(BallotAudit.event_id == event_id, Ballot.event_id == event_id)
    ):
        if ballot.round_id not in allowed:
            continue
        records.append(
            {
                **common,
                **round_fields(all_rounds[ballot.round_id]),
                "审计ID": audit.id,
                "操作时间": timestamp(audit.created_at),
                "操作者类型": "评委",
                "操作者ID": audit.judge_id,
                "操作": audit.action,
                "目标ID": audit.ballot_id,
                "变更前": audit_state({"before_revision": audit.before_revision}),
                "变更后": audit_state({"after_revision": audit.after_revision}),
                "请求ID": audit.request_id,
            }
        )
    return sorted(records, key=lambda r: (r["操作时间"], r["审计ID"]))


def export_csv(database, owner_id, event_id, kind, include_unpublished, clock):
    with database.read_snapshot() as session:
        event = owned_event(session, owner_id, event_id, draft_only=False)
        require_published(event)
        rule = session.scalar(select(EventSnapshot).where(EventSnapshot.event_id == event_id))
        _, rounds, results, _, ranking = public_data(session, event)
        now = clock()
        common = {
            "活动ID": event.id,
            "活动": event.title,
            "活动版本": event.version,
            "导出时间": timestamp(now),
            "规则版本": rule.rule_version,
        }
        selected = [r for r in rounds if include_unpublished or r.status == "PUBLISHED"]
        latest = {r.round_id: r for r in results}
        ranks = {r.entry_id: r.rank for r in ranking}
        judges = {j["id"]: j for j in rule.judges}
        bases = {
            r.id: {**common, **round_fields(r), **result_fields(latest.get(r.id), r, ranks)}
            for r in selected
        }
        if kind == "summary":
            rows = []
            for row in selected:
                result = latest.get(row.id)
                rows.append(
                    {
                        **bases[row.id],
                        "缺交评委编号": ",".join(
                            sorted(
                                judges[id_]["number"]
                                for id_ in result.calculation["missing_judge_ids"]
                            )
                        )
                        if result
                        else None,
                        "收评原因": result.reason if result else None,
                    }
                )
            content = csv_bytes(SUMMARY, rows)
        elif kind == "details":
            content = csv_bytes(
                DETAILS,
                detail_rows(session, event_id, selected, latest, judges, rule.scoring_rule, bases),
            )
        else:
            content = csv_bytes(AUDIT, audit_rows(session, event_id, common, rounds, selected))
        title = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]', "_", event.title).strip(" .") or "活动"
        label = {"summary": "成绩汇总", "details": "评分明细", "audit": "操作审计"}[kind]
        scope = "含未公布" if include_unpublished else "已公布"
        return content, f"{title}-{label}-{scope}-{now:%Y%m%dT%H%M%SZ}.csv"
