import { useState } from 'react'
import { Alert, App, Button, Col, Flex, List, Modal, Row, Space, Spin, Tag, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { Link, useParams, useSearchParams } from 'react-router'
import { adminConsole } from '../../api/admin'
import { eventStatusLabel, formatClock, roundStatusLabel } from '../format'
import { JudgePanel } from './JudgePanel'
import { useConsoleAction, useConsoleSnapshot, type ConsoleAction, type ConsoleSnapshot } from './data'
import { defaultRoundId, isTerminal, roundName, unfinishedHint, unfinishedRounds } from './model'
import { RoundList } from './RoundList'
import { RoundPanel } from './RoundPanel'
import { SnapshotFailure } from './SnapshotFailure'
import { ScreenManager } from './ScreenManager'

export function EventControlPage() {
  const { eventId = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const { modal } = App.useApp()
  const snapshot = useConsoleSnapshot(eventId, { poll: true })
  // 结束被拒时的待处理任务 ID；渲染时按最新快照映射为对象，未知 ID 原样显示。
  const [unfinished, setUnfinished] = useState<string[] | null>(null)
  const [screenOpen, setScreenOpen] = useState(false)
  const action = useConsoleAction(eventId, setUnfinished)

  if (snapshot.isPending) return <Spin className="page-spin" size="large" />
  if (!snapshot.data) return <SnapshotFailure eventId={eventId} error={snapshot.error} onRetry={() => void snapshot.refetch()} />

  const data = snapshot.data
  const { event, rounds } = data
  const live = event.status === 'READY' || event.status === 'RUNNING'
  const select = (roundId: string) => setParams({ round: roundId }, { replace: true })
  const selected = rounds.find(r => r.id === params.get('round')) ?? rounds.find(r => r.id === defaultRoundId(rounds))
  const done = rounds.filter(r => isTerminal(r.status)).length
  const run = action.mutateAsync
  // 默认选中随状态变化；操作某对象前先固定选中，操作后仍停留在该对象核对结果。
  const runRound = (roundAction: ConsoleAction) => {
    if (selected && params.get('round') !== selected.id) select(selected.id)
    return run(roundAction)
  }

  const confirmFinish = () => {
    const pending = unfinishedRounds(rounds)
    if (pending.length) {
      setUnfinished(pending.map(r => r.id))
      return
    }
    const version = event.version
    modal.confirm({
      title: `结束“${event.title}”？`,
      content: '结束后活动只读：不能再开评、收评或公布，评委不能再加入或提交，大屏切换为最终排名。全部记录保留。',
      okText: '确认结束',
      okButtonProps: { danger: true },
      onOk: () => run({ label: '结束活动', done: '活动已结束', run: () => adminConsole.finish(eventId, version) }).catch(() => undefined),
    })
  }

  const confirmArchive = () => {
    const version = event.version
    modal.confirm({
      title: `归档“${event.title}”？`,
      content: '归档只影响活动列表分类，评分、成绩与记录全部保留。',
      okText: '确认归档',
      onOk: () => run({ label: '归档', done: '活动已归档', run: () => adminConsole.archive(eventId, version) }).catch(() => undefined),
    })
  }

  return (
    <>
      <Flex justify="space-between" align="center" wrap gap={12} className="page-heading">
        <Space align="center" wrap>
          <Link to="/admin/events">活动列表</Link>
          <Typography.Text type="secondary">/</Typography.Text>
          <Typography.Title level={3} className="inline-title">{event.title}</Typography.Title>
          <Tag color={eventStatusLabel[event.status].color}>{eventStatusLabel[event.status].text}</Tag>
        </Space>
        <Space wrap>
          <Button onClick={() => setScreenOpen(true)}>大屏管理</Button>
          <Link to={`/admin/events/${eventId}/results`}><Button>成绩与记录</Button></Link>
          <Link to={`/admin/events/${eventId}/settings`}><Button>活动设置</Button></Link>
          {live && <Button danger disabled={action.isPending} onClick={confirmFinish}>结束活动</Button>}
          {event.status === 'FINISHED' && <Button disabled={action.isPending} onClick={confirmArchive}>归档</Button>}
        </Space>
      </Flex>

      <SyncBar snapshot={data} done={done} updatedAt={snapshot.dataUpdatedAt} fetching={snapshot.isFetching} failed={snapshot.isError} onRefresh={() => void snapshot.refetch()} />

      {!live && (
        <Alert
          type="info"
          showIcon
          className="form-alert"
          title={event.status === 'ARCHIVED' ? '活动已归档，评分只读' : '活动已结束，评分只读'}
          description="可以查看成绩与记录，也可继续管理大屏授权和展示内容。"
        />
      )}

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={6}>
          <RoundList rounds={rounds} results={data.results} selectedId={selected?.id} onSelect={select} />
        </Col>
        <Col xs={24} lg={12}>
          {selected && (
            <RoundPanel key={selected.id} snapshot={data} round={selected} readOnly={!live} busy={action.isPending} run={runRound} onSelect={select} />
          )}
        </Col>
        <Col xs={24} lg={6}>
          {selected && <JudgePanel snapshot={data} round={selected} resettable={live} />}
        </Col>
      </Row>

      {unfinished && (
        <UnfinishedDialog
          ids={unfinished}
          snapshot={data}
          onSelect={id => {
            select(id)
            setUnfinished(null)
          }}
          onClose={() => setUnfinished(null)}
        />
      )}
      {screenOpen && <ScreenManager snapshot={data} onClose={() => setScreenOpen(false)} />}
    </>
  )
}

interface SyncProps {
  snapshot: ConsoleSnapshot
  done: number
  updatedAt: number
  fetching: boolean
  failed: boolean
  onRefresh: () => void
}

function SyncBar({ snapshot, done, updatedAt, fetching, failed, onRefresh }: SyncProps) {
  return (
    <Flex gap={16} align="center" wrap className="console-meta">
      {snapshot.event.public_code && (
        <Typography.Text>
          活动码 <Typography.Text code copyable>{snapshot.event.public_code}</Typography.Text>
        </Typography.Text>
      )}
      <Typography.Text>完成 {done} / {snapshot.rounds.length} 个对象</Typography.Text>
      <Typography.Text type={failed ? 'warning' : 'secondary'}>
        {failed ? `同步失败，显示的是 ${formatClock(updatedAt)} 的数据` : `最后同步 ${formatClock(updatedAt)}`}
      </Typography.Text>
      <Button size="small" icon={<ReloadOutlined />} loading={fetching} onClick={onRefresh}>刷新</Button>
    </Flex>
  )
}

function UnfinishedDialog({ ids, snapshot, onSelect, onClose }: { ids: string[]; snapshot: ConsoleSnapshot; onSelect: (id: string) => void; onClose: () => void }) {
  const byId = new Map(snapshot.rounds.map(r => [r.id, r]))
  return (
    <Modal open title="还有对象未处理，不能结束活动" footer={<Button onClick={onClose}>知道了</Button>} onCancel={onClose}>
      <Typography.Paragraph type="secondary">全部对象须已公布、已跳过或标记无结果后才能结束。点击“定位”切换到对应对象。</Typography.Paragraph>
      <List
        size="small"
        dataSource={ids}
        renderItem={id => {
          const round = byId.get(id)
          if (!round) return <List.Item>任务 {id}（请刷新后核对）</List.Item>
          const label = roundStatusLabel[round.status]
          return (
            <List.Item actions={[<Button key="go" type="link" size="small" onClick={() => onSelect(id)}>定位</Button>]}>
              <Space wrap>
                <Typography.Text strong>{roundName(round)}</Typography.Text>
                <Tag color={label.color}>{label.text}</Tag>
                <Typography.Text type="secondary">{unfinishedHint(round.status)}</Typography.Text>
              </Space>
            </List.Item>
          )
        }}
      />
    </Modal>
  )
}
