import { useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { adminEvents } from '../../api/admin'
import { queryKeys } from '../../api/query'
import { useAdminSession } from '../session'

/** 单个活动的各项查询；键共用 adminEvent 前缀，写操作后整体失效。 */
export function useEventKeys(eventId: string) {
  const { admin } = useAdminSession()
  const base = queryKeys.adminEvent(admin.id, eventId)
  return {
    base,
    list: queryKeys.adminEvents(admin.id),
    info: [...base, 'info'] as const,
    entries: [...base, 'entries'] as const,
    judges: [...base, 'judges'] as const,
    check: [...base, 'publish-check'] as const,
    publication: [...base, 'publication'] as const,
  }
}

export function useEventInfo(eventId: string) {
  const keys = useEventKeys(eventId)
  return useQuery({ queryKey: keys.info, queryFn: ({ signal }) => adminEvents.get(eventId, signal) })
}

export function useEntries(eventId: string) {
  const keys = useEventKeys(eventId)
  return useQuery({ queryKey: keys.entries, queryFn: ({ signal }) => adminEvents.entries(eventId, signal) })
}

/** 评委列表只含凭证状态元数据，不含明文。 */
export function useJudges(eventId: string) {
  const keys = useEventKeys(eventId)
  return useQuery({ queryKey: keys.judges, queryFn: ({ signal }) => adminEvents.judges(eventId, signal) })
}

/** 活动或名单变化后刷新该活动全部数据及活动列表汇总。 */
export function useRefreshEvent(eventId: string) {
  const queryClient = useQueryClient()
  const { admin } = useAdminSession()
  const adminId = admin.id
  return useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.adminEvent(adminId, eventId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.adminEvents(adminId) }),
    ])
  }, [queryClient, adminId, eventId])
}
