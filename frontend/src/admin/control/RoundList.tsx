import { Card, Tag, Typography } from 'antd'
import type { PublicRound, ResultInfo } from '../../api/types'
import { roundStatusLabel } from '../format'
import { latestResult } from './model'

interface Props {
  rounds: PublicRound[]
  results: ResultInfo[]
  selectedId: string | undefined
  onSelect: (roundId: string) => void
}

/** 左侧对象列表，按展示顺序；每项显示状态、已交人数，已公布的显示最终成绩。 */
export function RoundList({ rounds, results, selectedId, onSelect }: Props) {
  return (
    <Card title={`参评对象（${rounds.length}）`} size="small" className="console-list">
      <ul className="round-list">
        {rounds.map(round => {
          const label = roundStatusLabel[round.status]
          const score = round.status === 'PUBLISHED' ? latestResult(results, round.id)?.calculation.final_score : null
          return (
            <li key={round.id}>
              <button
                type="button"
                className={`round-item${round.id === selectedId ? ' selected' : ''}`}
                aria-current={round.id === selectedId ? 'true' : undefined}
                onClick={() => onSelect(round.id)}
              >
                <span className="round-item-name">
                  <Typography.Text strong>{round.number}</Typography.Text> {round.name}
                </span>
                <span className="round-item-meta">
                  <Tag color={label.color}>{label.text}</Tag>
                  <Typography.Text type="secondary">
                    {score ? `成绩 ${score}` : `${round.submitted_count}/${round.expected_count}`}
                  </Typography.Text>
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </Card>
  )
}
