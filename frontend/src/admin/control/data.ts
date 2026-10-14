import { useCallback } from 'react'
import { App } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { adminConsole } from '../../api/admin'
import { ApiError } from '../../api/client'
import { describeError } from '../../api/errors'
import { queryKeys } from '../../api/query'
import type { AdminSnapshot } from '../../api/types'
import { clockOffset } from '../../lib/clock'
import { jittered, POLL_INTERVAL_MS, preferNewer } from '../../lib/polling'
import { useAdminSession, useReportError } from '../session'
import { isActive, parseUnfinishedIds } from './model'

/** 管理快照及收到时的服务端时钟偏差（倒计时在本地推算）。 */
export type ConsoleSnapshot = AdminSnapshot & { offsetMs: number }

function useSnapshotKey(eventId: string) {
  const { admin } = useAdminSession()
  return queryKeys.adminSnapshot(admin.id, eventId)
}

function pollInterval(data: ConsoleSnapshot | undefined): number | false {
  if (data && (data.event.status === 'FINISHED' || data.event.status === 'ARCHIVED')) return false
  const busy = !data || data.rounds.some(r => isActive(r.status))
  return jittered(busy ? POLL_INTERVAL_MS.admin : POLL_INTERVAL_MS.adminIdle)
}

/**
 * 管理快照：控制台轮询（后台标签页暂停、回到前台立即刷新），成绩页只在进入与手动刷新时读取。
 * 乱序到达的旧版本不覆盖已显示的状态。
 */
export function useConsoleSnapshot(eventId: string, { poll }: { poll: boolean }) {
  const key = useSnapshotKey(eventId)
  const queryClient = useQueryClient()
  return useQuery({
    queryKey: key,
    queryFn: async ({ signal }): Promise<ConsoleSnapshot> => {
      const next = await adminConsole.snapshot(eventId, signal)
      return preferNewer(queryClient.getQueryData<ConsoleSnapshot>(key), { ...next, offsetMs: clockOffset(next.server_time) })
    },
    refetchInterval: poll ? query => pollInterval(query.state.data) : false,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  })
}

/** 写操作后刷新快照，以及活动详情与列表汇总（状态、完成进度会变化）。 */
export function useRefreshConsole(eventId: string) {
  const queryClient = useQueryClient()
  const { admin } = useAdminSession()
  const key = useSnapshotKey(eventId)
  return useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: key }),
      queryClient.invalidateQueries({ queryKey: queryKeys.adminEvent(admin.id, eventId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.adminEvents(admin.id) }),
    ])
  }, [queryClient, key, admin.id, eventId])
}

export interface ConsoleAction {
  /** 用于提示，如“开始评分”。 */
  label: string
  /** 成功提示。 */
  done: string
  run: () => Promise<unknown>
}

/**
 * 控制操作均无幂等键：失败不自动重发。版本或状态冲突时刷新快照，由主持人看到最新状态后重新确认；
 * 超时、断网等结果未知时先刷新核对，并明确提示不要连续重复点击。
 */
export function useConsoleAction(eventId: string, onUnfinished: (roundIds: string[]) => void) {
  const refresh = useRefreshConsole(eventId)
  const report = useReportError()
  const { message, modal } = App.useApp()
  // 回调返回的刷新会被等待：快照更新前按钮保持禁用，避免对旧状态再次操作。
  return useMutation({
    mutationFn: (action: ConsoleAction) => action.run(),
    onSuccess: async (_, action) => {
      message.success(action.done)
      await refresh()
    },
    onError: async (error, action) => {
      const info = describeError(error)
      if (info.action === 'verify') {
        modal.warning({
          title: `${action.label}：结果未知`,
          content: `${info.message}。已重新读取最新状态，请核对对象状态后再决定是否重新操作，不要连续重复点击。${
            info.requestId ? `（请求编号：${info.requestId}）` : ''
          }`,
        })
        await refresh()
        return
      }
      report(error, `${action.label}失败`)
      if (error instanceof ApiError && error.code === 'UNFINISHED_ROUNDS') onUnfinished(parseUnfinishedIds(error.message))
      if (info.action !== 'fix') await refresh()
    },
  })
}
