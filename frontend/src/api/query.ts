import { QueryClient } from '@tanstack/react-query'
import { ApiError } from './client'

/**
 * 缓存键首段为角色，便于退出或撤销时整体清除；同一身份内才比较快照版本。
 * 身份段（管理员 ID、评委 ID、授权 ID）避免切换身份后读到上一身份的缓存。
 */
export const queryKeys = {
  admin: ['admin'] as const,
  judge: ['judge'] as const,
  screen: ['screen'] as const,
  adminEvents: (adminId: string) => ['admin', adminId, 'events'] as const,
  adminSnapshot: (adminId: string, eventId: string) => ['admin', adminId, 'snapshot', eventId] as const,
  judgeSnapshot: (judgeId: string, eventId: string) => ['judge', judgeId, 'snapshot', eventId] as const,
  screenSnapshot: (grantId: string) => ['screen', grantId, 'snapshot'] as const,
}

/** 只对读请求的网络错误和 503 有限重试；4xx 业务错误直接交给界面处理。 */
export function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (failureCount >= 2) return false
  return error instanceof ApiError && (error.status === 0 || error.status === 503)
}

export function retryDelay(attempt: number, error: unknown): number {
  if (error instanceof ApiError && error.retryAfter) return error.retryAfter * 1000
  return Math.min(1000 * 2 ** attempt, 8000)
}

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: shouldRetryQuery, retryDelay, staleTime: 0, refetchOnWindowFocus: true },
      // 写操作大多没有幂等键，失败后不自动重发；评分提交在业务层用原幂等键重试。
      mutations: { retry: false },
    },
  })
}
