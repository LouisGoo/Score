import type { BallotReceipt, PublishedRule } from '../api/types'
import { formatScore } from '../lib/decimal'

export function ScoreSummary({ scores, rule }: { scores: BallotReceipt['scores']; rule: PublishedRule }) {
  return <dl className="judge-score-list">{scores.map(score => <div key={score.criterion_id}>
    <dt>{rule.criteria.find(c => c.criterion_id === score.criterion_id)?.name ?? score.criterion_id}</dt>
    <dd>{score.value}</dd>
  </div>)}</dl>
}

export function Receipt({ receipt, rule }: { receipt: BallotReceipt; rule: PublishedRule }) {
  return <section className="judge-receipt" aria-label="服务端回执">
    <h3>评分已保存</h3><ScoreSummary scores={receipt.scores} rule={rule} />
    <p>个人总分：<strong>{formatScore(receipt.total_score)}</strong></p>
    <p>评分版本：{receipt.revision} · 规则版本：{receipt.rule_version}</p>
    <p>接收时间：<time dateTime={receipt.accepted_at}>{new Date(receipt.accepted_at).toLocaleString('zh-CN', { hour12: false })}</time></p>
    <p className="judge-muted">回执号：<span className="judge-receipt-id">{receipt.receipt_id}</span></p>
  </section>
}
