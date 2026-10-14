import { Card, Tag, Typography } from 'antd'
import { Link } from 'react-router'
import type { PublicRound } from '../../api/types'
import { formatClock } from '../format'
import type { ConsoleSnapshot } from './data'
import { judgeStatuses } from './model'

interface Props {
  snapshot: ConsoleSnapshot
  round: PublicRound
  /** 活动结束前可重置身份码（换手机时使用）。 */
  resettable: boolean
}

/** 右侧评委状态：只显示已交/未交与有效版本，不显示分数。在线状态依赖实时推送，暂不提供。 */
export function JudgePanel({ snapshot, round, resettable }: Props) {
  const started = round.status !== 'PENDING' && round.status !== 'SKIPPED'
  const rows = judgeStatuses(snapshot, round.id)
  return (
    <Card
      title="评委状态"
      size="small"
      extra={started && <Typography.Text>已交 {round.submitted_count} / {round.expected_count}</Typography.Text>}
      className="console-judges"
    >
      <ul className="judge-list">
        {rows.map(({ judge, revision, acceptedAt }) => (
          <li key={judge.id} className="judge-row">
            <span>
              <Typography.Text strong>{judge.number}</Typography.Text> {judge.name}
            </span>
            {!started ? (
              <Typography.Text type="secondary">—</Typography.Text>
            ) : revision > 0 ? (
              <span className="judge-state">
                <Tag color="green">已交</Tag>
                <Typography.Text type="secondary" className="judge-time">
                  {revision > 1 ? `第 ${revision} 版 · ` : ''}
                  {formatClock(acceptedAt)}
                </Typography.Text>
              </span>
            ) : (
              <Tag>未交</Tag>
            )}
          </li>
        ))}
      </ul>
      <Typography.Paragraph type="secondary" className="judge-note">
        {started ? '改分只更新版本，不增加已交人数。' : '开评后显示各评委已交状态。'}在线状态将在实时推送上线后显示。
        {resettable && (
          <>
            {' '}评委换手机请
            <Link to={`/admin/events/${snapshot.event.id}/settings?tab=judges`}>重置身份码</Link>。
          </>
        )}
      </Typography.Paragraph>
    </Card>
  )
}
