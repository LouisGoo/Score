import { useState } from 'react'
import { Alert, App, Button, Card, Flex, Result, Space, Spin, Steps, Tabs, Tag, Typography } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { adminEvents } from '../../api/admin'
import { describeError } from '../../api/errors'
import type { JudgeInfo, PublishResult } from '../../api/types'
import { eventStatusLabel } from '../format'
import { QueryFailure, useReportError } from '../session'
import { BasicPanel } from './BasicPanel'
import { CredentialDialog, type IssuedCredential } from './CredentialDialog'
import { useEventInfo, useEventKeys, useJudges, useRefreshEvent } from './data'
import { EntriesPanel } from './EntriesPanel'
import { JudgesPanel } from './JudgesPanel'
import { PublicEntryCard } from './PublicEntryCard'
import { PublishPanel } from './PublishPanel'
import { RulePanel } from './RulePanel'
import { SETUP_STEPS, isSetupTab, type SetupTab } from './steps'

interface Issued {
  items: IssuedCredential[]
  publicCode: string | null
}

export function EventSettingsPage() {
  const { eventId = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const report = useReportError()
  const { message, modal } = App.useApp()
  const keys = useEventKeys(eventId)
  const event = useEventInfo(eventId)
  const judges = useJudges(eventId)
  const refresh = useRefreshEvent(eventId)
  const queryClient = useQueryClient()
  // 发布返回的补码明文只保存在页面状态中；关闭对话框或离开页面即丢弃。
  const [issued, setIssued] = useState<Issued | null>(null)

  const status = event.data?.status
  const draft = status === 'DRAFT'
  const publication = useQuery({
    queryKey: keys.publication,
    queryFn: ({ signal }) => adminEvents.publication(eventId, signal),
    enabled: status !== undefined && !draft,
  })

  const tabParam = params.get('tab')
  const tab: SetupTab = isSetupTab(tabParam) ? tabParam : 'basic'
  const go = (next: SetupTab) => setParams({ tab: next }, { replace: true })

  const copy = useMutation({
    mutationFn: () => adminEvents.copy(eventId),
    onSuccess: created => {
      message.success('已复制为新草稿，身份码需重新设置')
      void refresh()
      navigate(`/admin/events/${created.id}/settings`)
    },
    onError: error => {
      report(error, '复制失败')
      void refresh()
    },
  })

  const remove = useMutation({
    mutationFn: () => adminEvents.remove(eventId),
    onSuccess: () => {
      message.success('草稿已删除')
      navigate('/admin/events', { replace: true })
      queryClient.removeQueries({ queryKey: keys.base })
      void queryClient.invalidateQueries({ queryKey: keys.list })
    },
    onError: error => {
      report(error, '删除失败')
      void refresh()
    },
  })

  const onPublished = (result: PublishResult, roster: JudgeInfo[]) => {
    const byId = new Map(roster.map(j => [j.id, j]))
    const items = result.generated_credentials.map(c => ({
      result: c,
      number: byId.get(c.judge_id)?.number ?? '',
      name: byId.get(c.judge_id)?.name ?? c.judge_id,
    }))
    if (items.length) setIssued({ items, publicCode: result.event.public_code })
    else message.success('活动已发布')
    go('publish')
  }

  if (event.isPending) return <Spin className="page-spin" size="large" />
  if (event.isError) {
    if (describeError(event.error).code === 'NOT_FOUND') {
      return <Result status="404" title="活动不存在或无权访问" extra={<Link to="/admin/events"><Button>返回活动列表</Button></Link>} />
    }
    return <QueryFailure error={event.error} onRetry={() => void event.refetch()} />
  }

  const info = event.data
  const label = eventStatusLabel[info.status]
  const currentStep = SETUP_STEPS.findIndex(s => s.key === tab)

  return (
    <>
      <Flex justify="space-between" align="center" wrap gap={12} className="page-heading">
        <Space align="center" wrap>
          <Link to="/admin/events">活动列表</Link>
          <Typography.Text type="secondary">/</Typography.Text>
          <Typography.Title level={3} className="inline-title">{info.title}</Typography.Title>
          <Tag color={label.color}>{label.text}</Tag>
        </Space>
        <Space wrap>
          {!draft && (
            <Link to={`/admin/events/${eventId}/control`}><Button type="primary">进入控制台</Button></Link>
          )}
          <Button
            loading={copy.isPending}
            onClick={() =>
              modal.confirm({
                title: '复制为新活动？',
                content: '复制配置与名单，生成新的草稿；不复制身份码、会话、评分和成绩。',
                okText: '复制',
                onOk: () => copy.mutateAsync().catch(() => undefined),
              })
            }
          >
            复制活动
          </Button>
          {draft && (
            <Button
              danger
              loading={remove.isPending}
              onClick={() =>
                modal.confirm({
                  title: `删除草稿“${info.title}”？`,
                  content: '删除后无法恢复，名单一并删除。',
                  okText: '删除',
                  okButtonProps: { danger: true },
                  onOk: () => remove.mutateAsync().catch(() => undefined),
                })
              }
            >
              删除草稿
            </Button>
          )}
        </Space>
      </Flex>

      {draft ? (
        <Steps
          current={currentStep}
          onChange={index => go(SETUP_STEPS[index].key)}
          items={SETUP_STEPS.map(s => ({ title: s.title }))}
          size="small"
          className="setup-steps"
        />
      ) : (
        <Alert
          className="form-alert"
          type="info"
          showIcon
          title="活动已发布，名单、评分规则与过程规则已冻结"
          description={
            info.status === 'READY' || info.status === 'RUNNING'
              ? '仍可在“评委与身份码”中重置身份码（换手机或泄露时使用）。大屏标题与主题将在控制台的大屏设置中修改。'
              : '活动已结束，所有配置只读。'
          }
        />
      )}

      <Card>
        <Tabs
          activeKey={tab}
          onChange={key => go(key as SetupTab)}
          items={SETUP_STEPS.map(step => ({
            key: step.key,
            label: !draft && step.key === 'publish' ? '发布信息' : step.title,
            children: renderPanel(step.key),
          }))}
          destroyOnHidden
        />
      </Card>

      {issued && (
        <CredentialDialog
          title="发布成功：自动生成的身份码"
          items={issued.items}
          publicCode={issued.publicCode}
          onClose={() => setIssued(null)}
        />
      )}
    </>
  )

  function renderPanel(key: SetupTab) {
    switch (key) {
      case 'basic':
        return <BasicPanel event={info} editable={draft} />
      case 'entries':
        return <EntriesPanel eventId={eventId} editable={draft} />
      case 'judges':
        return <JudgesPanel event={info} editable={draft} />
      case 'rule':
        return <RulePanel event={info} editable={draft} judgeCount={judges.data?.length ?? 0} publication={publication.data} />
      case 'publish':
        return draft ? (
          <PublishPanel event={info} onNavigate={go} onPublished={onPublished} />
        ) : (
          <PublicEntryCard event={info} />
        )
    }
  }
}
