import { Button, Card, Divider, Flex, Space, Spin, Table, Tag, Typography, type TableColumnsType, type TableProps } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { Link, useParams } from 'react-router'
import type { BallotReceipt, PublicRound, RankingInfo } from '../../api/types'
import { eventStatusLabel, formatClock, formatSeconds, roundStatusLabel } from '../format'
import { useConsoleSnapshot, type ConsoleSnapshot } from './data'
import { latestResult, receiptsFor, resultsFor } from './model'
import { ResultReview } from './ResultReview'
import { SnapshotFailure } from './SnapshotFailure'

/** 成绩与记录：排名、各对象收评结果与历次收评、评分版本记录。导出在后续批次提供。 */
export function EventResultsPage() {
  const { eventId = '' } = useParams()
  const snapshot = useConsoleSnapshot(eventId, { poll: false })

  if (snapshot.isPending) return <Spin className="page-spin" size="large" />
  if (!snapshot.data) return <SnapshotFailure eventId={eventId} error={snapshot.error} onRetry={() => void snapshot.refetch()} />

  const data = snapshot.data
  const { event } = data
  const final = event.status === 'FINISHED' || event.status === 'ARCHIVED'

  const rankingColumns: TableColumnsType<RankingInfo> = [
    { title: '名次', dataIndex: 'rank', width: 80 },
    { title: '编号', dataIndex: 'number', width: 120 },
    { title: '名称', dataIndex: 'name' },
    { title: '最终成绩', dataIndex: 'final_score', align: 'right', width: 140 },
  ]

  const roundColumns: TableColumnsType<PublicRound> = [
    { title: '编号', dataIndex: 'number', width: 100 },
    { title: '名称', dataIndex: 'name' },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (s: PublicRound['status']) => <Tag color={roundStatusLabel[s].color}>{roundStatusLabel[s].text}</Tag>,
    },
    {
      title: '有效 / 应交',
      width: 120,
      render: (_, r) => {
        const calc = latestResult(data.results, r.id)?.calculation
        return calc ? `${calc.valid_count} / ${calc.expected_count}` : `${r.submitted_count} / ${r.expected_count}（已交）`
      },
    },
    {
      title: '最终成绩',
      align: 'right',
      width: 140,
      render: (_, r) => {
        const score = latestResult(data.results, r.id)?.calculation.final_score
        if (!score || r.status === 'NO_RESULT') return '—'
        return r.status === 'PUBLISHED' ? score : <Typography.Text type="secondary">{score}（待公布）</Typography.Text>
      },
    },
    { title: '收评次数', width: 100, align: 'right', render: (_, r) => resultsFor(data.results, r.id).length },
  ]

  const expandable: TableProps<PublicRound>['expandable'] = {
    expandedRowRender: recordsOf(data),
    rowExpandable: round => resultsFor(data.results, round.id).length > 0 || receiptsFor(data, round.id).length > 0,
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
          <Typography.Text type="secondary">数据时间 {formatClock(snapshot.dataUpdatedAt)}</Typography.Text>
          <Button icon={<ReloadOutlined />} loading={snapshot.isFetching} onClick={() => void snapshot.refetch()}>刷新</Button>
          <Link to={`/admin/events/${eventId}/control`}><Button type="primary">返回控制台</Button></Link>
        </Space>
      </Flex>

      <Space orientation="vertical" size="large" className="full-width">
        <Card title={final ? '最终排名' : '当前排名'} size="small">
          <Table<RankingInfo>
            rowKey="entry_id"
            size="small"
            pagination={false}
            dataSource={data.ranking}
            columns={rankingColumns}
            locale={{ emptyText: '还没有已公布的成绩' }}
          />
          <Typography.Paragraph type="secondary" className="entry-note">
            仅已公布的对象参与排名，按两位小数成绩并列（1、2、2、4）；跳过与无结果的对象不参排。
          </Typography.Paragraph>
        </Card>

        <Card title="各对象成绩与记录" size="small">
          <Table<PublicRound>
            rowKey="id"
            size="small"
            pagination={false}
            dataSource={data.rounds}
            columns={roundColumns}
            scroll={{ x: 760 }}
            expandable={expandable}
          />
        </Card>
      </Space>
    </>
  )
}

type Receipt = BallotReceipt & { judgeId: string }

const recordsOf = (snapshot: ConsoleSnapshot) => (round: PublicRound) => <RoundRecords snapshot={snapshot} round={round} />

/** 历次收评（最新在前）与评分版本记录（按评委编号、版本）。 */
function RoundRecords({ snapshot, round }: { snapshot: ConsoleSnapshot; round: PublicRound }) {
  const results = resultsFor(snapshot.results, round.id)
  const judges = new Map(snapshot.judges.map(j => [j.id, j]))
  const receipts: Receipt[] = snapshot.judges.flatMap(j => receiptsFor(snapshot, round.id, j.id).map(r => ({ ...r, judgeId: j.id })))
  const newestFirst = results.map((_, i) => ({ result: results[results.length - 1 - i], index: results.length - 1 - i }))

  return (
    <div className="round-records">
      {newestFirst.map(({ result, index }) => (
        <div key={result.id} className="result-history">
          <Typography.Title level={5}>
            第 {index + 1} 次收评{index === results.length - 1 ? '（当前结果）' : ''}
          </Typography.Title>
          <ResultReview result={result} judges={snapshot.judges} rule={snapshot.rule} />
        </div>
      ))}
      {receipts.length > 0 && (
        <>
          <Divider titlePlacement="start" plain>评分版本记录</Divider>
          <Table<Receipt>
            rowKey="receipt_id"
            size="small"
            pagination={false}
            dataSource={receipts}
            columns={[
              {
                title: '评委',
                render: (_, r) => {
                  const judge = judges.get(r.judgeId)
                  return judge ? `${judge.number} ${judge.name}` : '—'
                },
              },
              { title: '版本', dataIndex: 'revision', width: 80, render: (v: number) => `第 ${v} 版` },
              { title: '个人总分', dataIndex: 'total_score', align: 'right', width: 100 },
              { title: '提交时间', dataIndex: 'accepted_at', width: 180, render: (v: string) => formatSeconds(v) },
              { title: '回执号', dataIndex: 'receipt_id', render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
            ]}
          />
        </>
      )}
    </div>
  )
}
