import { Alert, Descriptions, Space, Table, Tag, Tooltip, Typography, type TableColumnsType } from 'antd'
import type { JudgeInfo, PublishedRule, ResultBallot, ResultInfo } from '../../api/types'
import { formatScore } from '../../lib/decimal'
import { algorithmLabel, formatSeconds } from '../format'

interface Props {
  result: ResultInfo
  judges: JudgeInfo[]
  rule: PublishedRule
  /** 收评后待处理时提示能否公布；历史快照中不显示。 */
  showVerdict?: boolean
}

/** 收评快照核对：有效份数、缺交、各评委个人总分与剔除标记、最终分。只读，不提供改分入口。 */
export function ResultReview({ result, judges, rule, showVerdict = false }: Props) {
  const calc = result.calculation
  const byId = new Map(judges.map(j => [j.id, j]))
  const excluded = calc.ballots.filter(b => b.exclusion !== null).length
  // 快照按内部 ID 排列；按评委名单（编号序）展示，名单外的 ID（不应出现）附在末尾。
  const missing = [
    ...judges.filter(j => calc.missing_judge_ids.includes(j.id)).map(j => `${j.number} ${j.name}`),
    ...calc.missing_judge_ids.filter(id => !byId.has(id)),
  ]
  const ballots = [
    ...judges.flatMap(j => calc.ballots.filter(b => b.judge_id === j.id)),
    ...calc.ballots.filter(b => !byId.has(b.judge_id)),
  ]

  const columns: TableColumnsType<ResultBallot> = [
    {
      title: '评委',
      render: (_, b) => `${b.judge_number} ${byId.get(b.judge_id)?.name ?? ''}`,
    },
    ...(rule.mode === 'multi'
      ? rule.criteria.map(c => ({
          title: c.name,
          key: c.criterion_id,
          align: 'right' as const,
          render: (_: unknown, b: ResultBallot) => b.scores.find(s => s.criterion_id === c.criterion_id)?.value ?? '—',
        }))
      : []),
    {
      title: '个人总分',
      align: 'right',
      render: (_, b) => (
        <Tooltip title={`未舍入：${b.total}`}>
          <span>{formatScore(b.total)}</span>
        </Tooltip>
      ),
    },
    { title: '版本', dataIndex: 'revision', width: 72, render: (v: number) => `第 ${v} 版` },
    {
      title: '去极值',
      width: 110,
      render: (_, b) =>
        b.exclusion === 'highest' ? <Tag color="orange">剔除最高</Tag> : b.exclusion === 'lowest' ? <Tag color="orange">剔除最低</Tag> : '计入',
    },
  ]

  return (
    <Space orientation="vertical" size="middle" className="full-width">
      {showVerdict &&
        (calc.final_score === null ? (
          <Alert
            type="warning"
            showIcon
            title={`有效 ${calc.valid_count} 份，未达到最低有效份数 K=${calc.minimum_ballots}，不能公布`}
            description="可以重开补评（保留已交评分），或填写原因标记无结果。"
          />
        ) : (
          <Alert type="success" showIcon title={`可以公布：最终成绩 ${calc.final_score}`} description="请核对有效份数、缺交与剔除情况后公布。" />
        ))}
      <Descriptions
        size="small"
        bordered
        column={{ xs: 1, md: 2 }}
        items={[
          {
            key: 'final',
            label: '最终成绩',
            children: calc.final_score ?? <Typography.Text type="secondary">未形成成绩</Typography.Text>,
          },
          { key: 'valid', label: '有效 / 应交', children: `${calc.valid_count} / ${calc.expected_count}` },
          { key: 'k', label: '最低有效份数 K', children: calc.minimum_ballots },
          { key: 'algorithm', label: '汇总算法', children: algorithmLabel[calc.algorithm] + (excluded ? `（剔除 ${excluded} 份）` : '') },
          {
            key: 'closed',
            label: '收评',
            children: `${result.source === 'deadline' ? '到时自动收评' : '手动收评'} · ${formatSeconds(result.closed_at)}`,
          },
          { key: 'reason', label: '收评原因', children: result.reason || '—' },
        ]}
      />
      {missing.length > 0 && (
        <Typography.Text type="secondary">
          缺交 {missing.length} 人（不计零分）：
          {missing.join('、')}
        </Typography.Text>
      )}
      <Table<ResultBallot>
        rowKey="ballot_id"
        size="small"
        pagination={false}
        dataSource={ballots}
        columns={columns}
        scroll={{ x: 'max-content' }}
        locale={{ emptyText: '没有有效评分' }}
      />
    </Space>
  )
}
