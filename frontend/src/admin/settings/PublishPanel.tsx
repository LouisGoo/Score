import { useState } from 'react'
import { Alert, App, Button, Descriptions, Flex, List, Space, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { useMutation, useQuery } from '@tanstack/react-query'
import { adminEvents } from '../../api/admin'
import { ApiError, type ApiIssue } from '../../api/client'
import type { EventInfo, JudgeInfo, PublishResult } from '../../api/types'
import { QueryFailure, useReportError } from '../session'
import { useEventKeys, useJudges, useRefreshEvent } from './data'
import { SETUP_STEPS, tabForField, type SetupTab } from './steps'

interface Props {
  event: EventInfo
  onNavigate: (tab: SetupTab) => void
  /** 发布成功后由页面持有补码明文，避免本面板随状态切换卸载而丢失。 */
  onPublished: (result: PublishResult, judges: JudgeInfo[]) => void
}

export function PublishPanel({ event, onNavigate, onPublished }: Props) {
  const keys = useEventKeys(event.id)
  const judges = useJudges(event.id)
  const refresh = useRefreshEvent(event.id)
  const report = useReportError()
  const { modal } = App.useApp()
  const [rejected, setRejected] = useState<ApiIssue[] | null>(null)

  const check = useQuery({ queryKey: keys.check, queryFn: ({ signal }) => adminEvents.publishCheck(event.id, signal) })

  const publish = useMutation({
    // 响应含补码明文：交给页面状态后即从变更缓存移除。
    gcTime: 0,
    mutationFn: () => adminEvents.publish(event.id),
    onSuccess: result => {
      setRejected(null)
      onPublished(result, judges.data ?? [])
      publish.reset()
      void refresh()
    },
    onError: async error => {
      const info = report(error, '发布失败')
      if (error instanceof ApiError && error.code === 'PUBLISH_INVALID') {
        setRejected(error.issues)
        void check.refetch()
        return
      }
      if (info.action === 'verify' || info.code === 'SERVICE_UNAVAILABLE') {
        // 发布无幂等键：先查发布记录确认是否已生效，不自动重发。
        const published = await adminEvents.publication(event.id).then(
          () => true,
          (e: unknown) => (e instanceof ApiError && e.code === 'NOT_FOUND' ? false : null),
        )
        modal.warning(
          published
            ? {
                title: '活动已发布',
                content: '发布已经完成，但本次自动生成的身份码明文未能取回。请在“评委与身份码”中为未拿到身份码的评委重置并分发。',
              }
            : published === false
              ? { title: '活动未发布', content: '服务端没有发布记录，可以核对后重新发布。' }
              : { title: '发布结果未知', content: '暂时无法确认是否已发布，请稍后刷新页面核对，不要重复点击发布。' },
        )
      }
      void refresh()
    },
  })

  if (check.isError) return <QueryFailure error={check.error} onRetry={() => void check.refetch()} title="发布检查失败" />

  const result = check.data
  const issues = rejected ?? result?.issues ?? []
  const confirmPublish = () =>
    modal.confirm({
      title: `发布“${event.title}”？`,
      width: 520,
      content: (
        <>
          <p>发布后对象名单、评委名单、评分规则与过程规则全部冻结，不能再修改；如需调整只能复制为新活动。</p>
          {result && result.missing_credential_count > 0 && (
            <p>将为 {result.missing_credential_count} 位未设置身份码的评委自动生成身份码，明文只显示一次，请准备好记录。</p>
          )}
        </>
      ),
      okText: '确认发布',
      onOk: () => publish.mutateAsync().catch(() => undefined),
    })

  return (
    <Space orientation="vertical" size="large" className="full-width">
      <Flex justify="space-between" align="center">
        <Typography.Text type="secondary">检查基于当前已保存的配置；未保存的修改不会被检查。</Typography.Text>
        <Button icon={<ReloadOutlined />} loading={check.isFetching} onClick={() => { setRejected(null); void check.refetch() }}>
          重新检查
        </Button>
      </Flex>

      {result && (
        <Descriptions
          bordered
          size="small"
          column={{ xs: 1, md: 4 }}
          items={[
            { key: 'entries', label: '参评对象', children: result.entry_count },
            { key: 'judges', label: '评委', children: result.judge_count },
            { key: 'k', label: '最低有效份数 K', children: result.minimum_ballots ?? '—' },
            { key: 'missing', label: '待生成身份码', children: result.missing_credential_count },
          ]}
        />
      )}

      {result && issues.length === 0 && result.can_publish && (
        <Alert
          type="success"
          showIcon
          title="检查通过，可以发布"
          description={
            result.missing_credential_count > 0
              ? `发布时将为 ${result.missing_credential_count} 位评委自动生成身份码。`
              : '所有评委均已设置身份码。'
          }
        />
      )}

      {issues.length > 0 && (
        <Alert
          type="error"
          showIcon
          title={rejected ? '发布被拒绝：配置不满足发布条件' : `还有 ${issues.length} 个问题需要处理`}
          description={
            <List<ApiIssue>
              size="small"
              dataSource={issues}
              renderItem={issue => {
                const tab = tabForField(issue.field)
                return (
                  <List.Item
                    actions={[
                      <Button key="go" type="link" size="small" onClick={() => onNavigate(tab)}>
                        去“{SETUP_STEPS.find(s => s.key === tab)!.title}”
                      </Button>,
                    ]}
                  >
                    {issue.message}
                  </List.Item>
                )
              }}
            />
          }
        />
      )}

      <Button
        type="primary"
        size="large"
        disabled={!result?.can_publish || issues.length > 0 || check.isFetching}
        loading={publish.isPending}
        onClick={confirmPublish}
      >
        发布活动
      </Button>
    </Space>
  )
}
