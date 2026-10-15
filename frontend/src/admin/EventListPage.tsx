import { useMemo, useState } from 'react'
import { App, Button, Flex, Progress, Segmented, Space, Table, Tag, Typography, type TableColumnsType } from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router'
import { adminEvents } from '../api/admin'
import { queryKeys } from '../api/query'
import type { EventListItem, EventStatus } from '../api/types'
import { eventStatusLabel, formatTime } from './format'
import { QueryFailure, useAdminSession, useReportError } from './session'

type Filter = 'active' | 'DRAFT' | 'live' | 'FINISHED' | 'ARCHIVED' | 'all'

const filters: { value: Filter; label: string; match: (s: EventStatus) => boolean }[] = [
  { value: 'active', label: '未归档', match: s => s !== 'ARCHIVED' },
  { value: 'DRAFT', label: '草稿', match: s => s === 'DRAFT' },
  { value: 'live', label: '已发布/进行中', match: s => s === 'READY' || s === 'RUNNING' },
  { value: 'FINISHED', label: '已结束', match: s => s === 'FINISHED' },
  { value: 'ARCHIVED', label: '已归档', match: s => s === 'ARCHIVED' },
  { value: 'all', label: '全部', match: () => true },
]

export function EventListPage() {
  const { admin } = useAdminSession()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const report = useReportError()
  const { message, modal } = App.useApp()
  const [filter, setFilter] = useState<Filter>('active')
  const listKey = queryKeys.adminEvents(admin.id)

  const events = useQuery({ queryKey: listKey, queryFn: ({ signal }) => adminEvents.list(signal) })
  const refresh = () => queryClient.invalidateQueries({ queryKey: listKey })

  const copy = useMutation({
    mutationFn: (event: EventListItem) => adminEvents.copy(event.id),
    onSuccess: created => {
      message.success('已复制为新草稿，身份码需重新设置')
      void refresh()
      navigate(`/admin/events/${created.id}/settings`)
    },
    onError: error => {
      // 复制没有幂等键：结果未知时只刷新列表供核对，不自动重发。
      if (report(error, '复制失败').action !== 'fix') void refresh()
    },
  })

  const remove = useMutation({
    mutationFn: (event: EventListItem) => adminEvents.remove(event.id),
    onSuccess: () => {
      message.success('草稿已删除')
      void refresh()
    },
    onError: error => {
      report(error, '删除失败')
      void refresh()
    },
  })

  const confirmCopy = (event: EventListItem) =>
    modal.confirm({
      title: `复制“${event.title}”？`,
      content: '复制活动配置、对象与评委名单，生成新的草稿；不复制身份码、会话、评分和成绩。',
      okText: '复制',
      onOk: () => copy.mutateAsync(event).catch(() => undefined),
    })

  const confirmRemove = (event: EventListItem) =>
    modal.confirm({
      title: `删除草稿“${event.title}”？`,
      content: '删除后无法恢复，名单一并删除。',
      okText: '删除',
      okButtonProps: { danger: true },
      onOk: () => remove.mutateAsync(event).catch(() => undefined),
    })

  const rows = useMemo(() => {
    const match = filters.find(f => f.value === filter)!.match
    return (events.data ?? []).filter(e => match(e.status))
  }, [events.data, filter])

  const columns: TableColumnsType<EventListItem> = [
    {
      title: '活动',
      dataIndex: 'title',
      render: (_, e) => (
        <Space orientation="vertical" size={0}>
          <Link to={`/admin/events/${e.id}/settings`} target='_blank'>{e.title}</Link>
          {e.organization && <Typography.Text type="secondary">{e.organization}</Typography.Text>}
        </Space>
      ),
    },
    { title: '计划时间', dataIndex: 'planned_at', width: 160, render: (v: string | null) => formatTime(v) },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (s: EventStatus) => <Tag color={eventStatusLabel[s].color}>{eventStatusLabel[s].text}</Tag>,
    },
    { title: '对象', dataIndex: 'entry_count', width: 70, align: 'right' },
    { title: '评委', dataIndex: 'judge_count', width: 70, align: 'right' },
    {
      title: '完成进度',
      width: 190,
      render: (_, e) =>
        e.round_count === 0 ? (
          <Typography.Text type="secondary">未发布</Typography.Text>
        ) : (
          <Flex gap={8} align="center">
            <Progress
              percent={Math.round((e.finished_round_count / e.round_count) * 100)}
              showInfo={false}
              size="small"
              className="list-progress"
            />
            <Typography.Text>{e.finished_round_count}/{e.round_count}</Typography.Text>
          </Flex>
        ),
    },
    {
      title: '操作',
      width: 230,
      render: (_, e) => (
        <Space size={4} wrap>
          <Link to={`/admin/events/${e.id}/settings`} target='_blank'>
            <Button size="small" type="link">{e.status === 'DRAFT' ? '编辑' : '设置'}</Button>
          </Link>
          {e.status !== 'DRAFT' && (
            <Link to={`/admin/events/${e.id}/control`} target='_blank'>
              <Button size="small" type="link">控制台</Button>
            </Link>
          )}
          <Button size="small" type="link" onClick={() => confirmCopy(e)} disabled={copy.isPending}>复制</Button>
          {e.status === 'DRAFT' && (
            <Button size="small" type="link" danger onClick={() => confirmRemove(e)} disabled={remove.isPending}>
              删除
            </Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <>
      <Flex justify="space-between" align="center" wrap gap={12} className="page-heading">
        <Typography.Title level={3}>活动列表</Typography.Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void refresh()} loading={events.isFetching}>刷新</Button>
          <Link to="/admin/events/new">
            <Button type="primary" icon={<PlusOutlined />}>创建活动</Button>
          </Link>
        </Space>
      </Flex>
      <Segmented<Filter> options={filters} value={filter} onChange={setFilter} className="list-filter" />
      {events.isError ? (
        <QueryFailure error={events.error} onRetry={() => void events.refetch()} />
      ) : (
        <Table<EventListItem>
          rowKey="id"
          columns={columns}
          dataSource={rows}
          loading={events.isPending}
          pagination={{ pageSize: 20, hideOnSinglePage: true }}
          scroll={{ x: 900 }}
          locale={{ emptyText: events.data?.length ? '没有符合条件的活动' : '还没有活动，点击“创建活动”开始' }}
        />
      )}
    </>
  )
}
