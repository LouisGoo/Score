import { useCallback, useEffect, type ReactNode } from 'react'
import { Alert, Button, Spin } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Navigate, useNavigate } from 'react-router'
import { judgeAuth } from '../api/judge'
import { ApiError } from '../api/client'
import { describeError } from '../api/errors'
import { queryKeys } from '../api/query'
import type { JudgeSessionInfo } from '../api/types'
import { clearJudgeDrafts } from '../lib/drafts'
import { clearJudgeSubmissions } from './storage'

export const sessionKey = ['judge', 'session'] as const

export function useJudgeSession() {
  return useQuery({
    queryKey: sessionKey,
    queryFn: async () => {
      try { return await judgeAuth.me() }
      catch (error) {
        if (error instanceof ApiError && error.status === 401) return null
        throw error
      }
    },
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })
}

export function useForgetJudge() {
  const client = useQueryClient()
  return useCallback((preserveSessionDuringNavigation = false) => {
    const session = client.getQueryData<JudgeSessionInfo | null>(sessionKey)
    if (session) {
      try { clearJudgeDrafts(session.judge.event_id, session.judge.id) } catch { /* Storage may be unavailable. */ }
      clearJudgeSubmissions(session.judge.event_id, session.judge.id)
    }
    judgeAuth.forget()
    // 失效跳转时先清本机草稿与令牌，加入页接管后清查询缓存，避免过渡中的 Guard 再次重定向。
    if (!preserveSessionDuringNavigation) {
      void client.cancelQueries({ queryKey: queryKeys.judge })
      client.removeQueries({ queryKey: queryKeys.judge, predicate: q => q.queryKey[1] !== 'session' })
      client.setQueryData(sessionKey, null)
    }
  }, [client])
}

export function JudgeError({ error }: { error: unknown }) {
  const info = describeError(error)
  return <Alert type="error" showIcon title={info.message} description={<>
    {info.hint}{info.requestId && <div className="request-id">请求编号：{info.requestId}</div>}
  </>} />
}

export function ExpiredSession({ publicCode }: { publicCode?: string }) {
  const navigate = useNavigate()
  const forget = useForgetJudge()
  useEffect(() => {
    forget(true)
    navigate(publicCode ? `/join/${encodeURIComponent(publicCode)}` : '/join', {
      replace: true, state: { expired: true },
    })
  }, [forget, navigate, publicCode])
  return <Alert type="warning" title="身份已失效，请重新加入活动" />
}

export function JudgeGuard({ eventId, children }: { eventId: string; children: (session: JudgeSessionInfo) => ReactNode }) {
  const session = useJudgeSession()
  if (session.isPending) return <Spin className="page-spin" />
  if (session.error) return <><JudgeError error={session.error} /><Button onClick={() => void session.refetch()}>重新确认身份</Button></>
  if (!session.data) return <ExpiredSession />
  if (session.data.judge.event_id !== eventId) return <Navigate to={`/judge/events/${session.data.judge.event_id}`} replace />
  return children(session.data)
}
