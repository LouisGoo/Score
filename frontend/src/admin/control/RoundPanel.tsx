import { useState } from 'react'
import { Alert, App, Button, Card, Descriptions, Flex, Progress, Space, Statistic, Tag, Tooltip, Typography } from 'antd'
import { CaretRightOutlined, PauseOutlined, StopOutlined } from '@ant-design/icons'
import { adminConsole } from '../../api/admin'
import type { PublicRound } from '../../api/types'
import { formatCountdown, pausedRemainingMs, remainingMs } from '../../lib/clock'
import { useNow } from '../../lib/useNow'
import { formatDuration, roundStatusLabel } from '../format'
import type { ConsoleAction, ConsoleSnapshot } from './data'
import { activeRound, latestResult, nextPendingRound, roundName, ruleSummary } from './model'
import { ReasonDialog, type ReasonRequest } from './ReasonDialog'
import { ResultReview } from './ResultReview'

interface Props {
  snapshot: ConsoleSnapshot
  round: PublicRound
  /** 活动已结束或归档：只展示，不提供控制按钮。 */
  readOnly: boolean
  busy: boolean
  run: (action: ConsoleAction) => Promise<unknown>
  onSelect: (roundId: string) => void
}

/** 当前对象的状态、倒计时与控制按钮。主持人不能填写或修改评委分数。 */
export function RoundPanel({ snapshot, round, readOnly, busy, run, onSelect }: Props) {
  const { modal } = App.useApp()
  const [dialog, setDialog] = useState<ReasonRequest | null>(null)
  const now = useNow(round.status === 'OPEN' && round.deadline_at !== null)
  const { event, rule } = snapshot
  const name = roundName(round)
  const active = activeRound(snapshot.rounds)
  const blocker = active && active.id !== round.id ? active : undefined
  const result = latestResult(snapshot.results, round.id)
  const next = nextPendingRound(snapshot.rounds, round.id)
  const missing = round.expected_count - round.submitted_count
  const label = roundStatusLabel[round.status]
  // 动作携带确认时看到的任务版本；期间如被他人改变，服务端返回版本冲突并刷新。
  const version = round.version

  const left =
    round.status === 'OPEN' ? remainingMs(round.deadline_at, snapshot.offsetMs, now) : round.status === 'PAUSED' ? pausedRemainingMs(round.remaining_seconds) : null
  const expired = round.status === 'OPEN' && left === 0

  const act = (title: string, done: string, call: () => Promise<unknown>) => run({ label: title, done, run: call }).catch(() => undefined)

  const confirmOpen = () =>
    modal.confirm({
      title: `开始评分：${name}`,
      width: 520,
      content: (
        <>
          <Descriptions
            size="small"
            column={1}
            items={[
              { key: 'n', label: '应交人数', children: `${round.expected_count} 位评委` },
              { key: 'rule', label: '评分规则', children: ruleSummary(rule) },
              { key: 'time', label: '评分时长', children: event.duration_seconds ? `${formatDuration(event.duration_seconds)}，可暂停` : '不限时，由主持人收评' },
              { key: 'rev', label: '改分', children: event.allow_revisions ? '开放期内允许改分' : '提交后不能改分' },
            ]}
          />
          <Typography.Paragraph type="secondary" className="dialog-note">开评后评委手机自动切换到该对象，大屏切换到进度页。</Typography.Paragraph>
        </>
      ),
      okText: '确认开评',
      onOk: () => act('开始评分', `已开始评分：${name}`, () => adminConsole.open(round.id, version)),
    })

  const confirmPublish = () => {
    if (!result?.calculation.final_score) return
    const calc = result.calculation
    const excluded = calc.ballots.filter(b => b.exclusion !== null).length
    modal.confirm({
      title: `公布成绩：${name}`,
      content: (
        <>
          <p>
            最终成绩 <Typography.Text strong>{calc.final_score}</Typography.Text>，有效 {calc.valid_count} / 应交 {calc.expected_count}
            {excluded ? `，剔除 ${excluded} 份` : ''}
            {calc.missing_judge_ids.length ? `，缺交 ${calc.missing_judge_ids.length} 人` : ''}。
          </p>
          <p>公布后成绩不可修改，计入排名，大屏切换到成绩页。</p>
        </>
      ),
      okText: '确认公布',
      onOk: () => act('公布成绩', `已公布：${name}`, () => adminConsole.publishResult(round.id, version)),
    })
  }

  const askSkip = () =>
    setDialog({
      title: `跳过：${name}`,
      okText: '确认跳过',
      danger: true,
      description: '跳过后该对象不再评分、不参与排名，且不能恢复。',
      reasonLabel: '跳过原因',
      reasonRequired: true,
      placeholder: '如：对象缺席',
      submit: ({ reason }) => run({ label: '跳过', done: `已跳过：${name}`, run: () => adminConsole.skip(round.id, version, reason!) }),
    })

  const askClose = () =>
    setDialog({
      title: `收评：${name}`,
      okText: '确认收评',
      description:
        missing > 0 ? (
          <Alert
            type="warning"
            showIcon
            title={`未收齐：已交 ${round.submitted_count} / 应交 ${round.expected_count}`}
            description={
              <>
                缺交不计零分，按实际有效评分计算。
                {round.submitted_count < rule.minimum_ballots && `已交少于最低有效份数 K=${rule.minimum_ballots}，收评后不能公布，只能重开补评或标记无结果。`}
              </>
            }
          />
        ) : (
          <Typography.Paragraph>已收齐 {round.expected_count} 份评分。收评后冻结结果，核对后再公布。</Typography.Paragraph>
        ),
      reasonLabel: '收评原因',
      reasonRequired: missing > 0,
      placeholder: missing > 0 ? '如：评委临时离场' : '可不填',
      submit: ({ reason }) => run({ label: '收评', done: `已收评：${name}`, run: () => adminConsole.close(round.id, version, reason) }),
    })

  const askReopen = () =>
    setDialog({
      title: `重开补评：${name}`,
      okText: '确认重开',
      description: '保留已交评分和历次收评记录，未交评委可以补交；是否允许改分沿用活动规则。',
      reasonLabel: '重开原因',
      reasonRequired: true,
      placeholder: '如：有评委未及时提交',
      duration: event.duration_seconds ?? null,
      submit: ({ reason, durationSeconds }) =>
        run({ label: '重开补评', done: `已重开：${name}`, run: () => adminConsole.reopen(round.id, version, reason!, durationSeconds) }),
    })

  const askNoResult = () =>
    setDialog({
      title: `标记无结果：${name}`,
      okText: '确认标记',
      danger: true,
      description: '标记后该对象不形成成绩、不参与排名，且不能再重开。',
      reasonLabel: '无结果原因',
      reasonRequired: true,
      submit: ({ reason }) => run({ label: '标记无结果', done: `已标记无结果：${name}`, run: () => adminConsole.noResult(round.id, version, reason!) }),
    })

  const blockedTip = blocker ? `请先收评“${roundName(blocker)}”` : undefined

  return (
    <Card className="console-round">
      <Flex justify="space-between" align="start" gap={12} wrap>
        <div>
          <Typography.Title level={4} className="inline-title">{name}</Typography.Title>
          {round.description && (
            <Typography.Paragraph type="secondary" ellipsis={{ rows: 2, expandable: true }} className="round-description">
              {round.description}
            </Typography.Paragraph>
          )}
        </div>
        <Tag color={label.color} className="round-status">{label.text}</Tag>
      </Flex>

      <Flex gap={32} wrap className="round-stats">
        <div>
          <Statistic title="已交 / 应交" value={round.submitted_count} suffix={`/ ${round.expected_count}`} />
          <Progress percent={round.expected_count ? Math.round((round.submitted_count / round.expected_count) * 100) : 0} showInfo={false} size="small" />
        </div>
        <Statistic title="最低有效份数 K" value={rule.minimum_ballots} />
        <Statistic
          title={round.status === 'PAUSED' ? '暂停时剩余' : round.status === 'OPEN' ? '剩余时间' : '评分时长'}
          value={round.status === 'OPEN' || round.status === 'PAUSED' ? formatCountdown(left) : formatDuration(event.duration_seconds)}
          className={expired ? 'countdown-expired' : undefined}
        />
      </Flex>

      {expired && (
        <Alert
          type="warning"
          showIcon
          className="form-alert"
          title="已到截止时间，评委不能再提交"
          description="后台会自动收评，也可以立即手动收评。"
        />
      )}
      {round.status === 'PAUSED' && (
        <Alert type="info" showIcon className="form-alert" title="评分已暂停" description="暂停期间评委不能提交；恢复后按剩余时间重新计算截止。" />
      )}

      {!readOnly && (
        <Space wrap className="round-actions">
          {round.status === 'PENDING' && (
            <>
              <Tooltip title={blockedTip}>
                <Button type="primary" size="large" icon={<CaretRightOutlined />} disabled={!!blocker || busy} onClick={confirmOpen}>
                  开始评分
                </Button>
              </Tooltip>
              <Button disabled={busy} onClick={askSkip}>跳过</Button>
            </>
          )}
          {round.status === 'OPEN' && (
            <>
              <Button type="primary" size="large" icon={<StopOutlined />} disabled={busy} onClick={askClose}>收评</Button>
              {!expired && (
                <Button size="large" icon={<PauseOutlined />} disabled={busy} onClick={() => void act('暂停', `已暂停：${name}`, () => adminConsole.pause(round.id, version))}>
                  暂停
                </Button>
              )}
            </>
          )}
          {round.status === 'PAUSED' && (
            <>
              <Button type="primary" size="large" icon={<CaretRightOutlined />} disabled={busy} onClick={() => void act('恢复', `已恢复：${name}`, () => adminConsole.resume(round.id, version))}>
                恢复
              </Button>
              <Button size="large" icon={<StopOutlined />} disabled={busy} onClick={askClose}>收评</Button>
            </>
          )}
          {round.status === 'CLOSED' && (
            <>
              {result?.calculation.final_score && (
                <Button type="primary" size="large" disabled={busy} onClick={confirmPublish}>公布成绩</Button>
              )}
              <Tooltip title={blockedTip}>
                <Button disabled={!!blocker || busy} onClick={askReopen}>重开补评</Button>
              </Tooltip>
              {result && !result.calculation.final_score && (
                <Button danger disabled={busy} onClick={askNoResult}>标记无结果</Button>
              )}
            </>
          )}
        </Space>
      )}

      {result && (round.status === 'CLOSED' || round.status === 'PUBLISHED' || round.status === 'NO_RESULT') && (
        <div className="round-result">
          <Typography.Title level={5}>
            {round.status === 'CLOSED' ? '结果核对' : '收评结果'}
          </Typography.Title>
          <ResultReview result={result} judges={snapshot.judges} rule={rule} showVerdict={round.status === 'CLOSED'} />
        </div>
      )}
      {round.status === 'SKIPPED' && <Typography.Paragraph type="secondary">该对象已跳过，不参与排名。</Typography.Paragraph>}

      {!readOnly && !active && next && round.status !== 'PENDING' && (
        <Button type="link" className="next-round" onClick={() => onSelect(next.id)}>
          下一个待评对象：{roundName(next)}
        </Button>
      )}

      {dialog && <ReasonDialog request={dialog} busy={busy} onClose={() => setDialog(null)} />}
    </Card>
  )
}
