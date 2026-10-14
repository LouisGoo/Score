import { createContext, useCallback, useContext, useEffect, type ReactNode } from 'react'
import { App, Alert, Button, Result, Spin } from 'antd'
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router'
import { adminAuth } from '../api/admin'
import { describeError, type ErrorDescription } from '../api/errors'
import { queryKeys } from '../api/query'
import type { SessionInfo } from '../api/types'

const SessionContext = createContext<SessionInfo | null>(null)

export function useAdminSession(): SessionInfo {
  const session = useContext(SessionContext)
  if (!session) throw new Error('useAdminSession 只能在 AdminGuard 内使用')
  return session
}

export const LOGIN_PATH = '/admin/login'

/** 只接受站内管理端路径作为登录后跳转目标，避免开放重定向。 */
export function safeNext(value: string | null): string {
  if (!value || !value.startsWith('/admin/') || value.startsWith('//') || value.startsWith(LOGIN_PATH)) {
    return '/admin/events'
  }
  return value
}

export function loginUrl(next: string): string {
  return `${LOGIN_PATH}?next=${encodeURIComponent(next)}`
}

/** 清除主办方的业务缓存；会话条目保留给已订阅的组件，由调用方另行置值。 */
export function clearAdminData(queryClient: QueryClient) {
  queryClient.removeQueries({ queryKey: queryKeys.admin, predicate: q => q.queryKey[1] !== queryKeys.adminSession[1] })
}

/**
 * 清空主办方身份的内存 CSRF 与全部缓存；退出、会话失效时调用。
 * 会话缓存置为 null（已退出）而非移除，使页头等订阅者立即更新。
 */
export function useForgetAdmin() {
  const queryClient = useQueryClient()
  return useCallback(() => {
    adminAuth.forget()
    clearAdminData(queryClient)
    queryClient.setQueryData<SessionInfo | null>(queryKeys.adminSession, null)
  }, [queryClient])
}

/** 会话查询：null 表示本页已退出或已确认失效。 */
export function useSessionQuery(options: { enabled?: boolean; retry?: false } = {}) {
  return useQuery<SessionInfo | null>({
    queryKey: queryKeys.adminSession,
    queryFn: () => adminAuth.me(),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    ...options,
  })
}

/**
 * 统一处理主办方页面的接口错误：会话失效时清空缓存并回登录页，其余显示服务端提示与请求编号。
 * 返回错误说明，调用方据 action 决定是否刷新数据（refresh/verify）。
 */
export function useReportError() {
  const { message } = App.useApp()
  const forget = useForgetAdmin()
  const navigate = useNavigate()
  const location = useLocation()
  return useCallback(
    (error: unknown, context?: string): ErrorDescription => {
      const info = describeError(error)
      if (info.action === 'relogin') {
        forget()
        message.warning('登录已失效，请重新登录')
        navigate(loginUrl(location.pathname + location.search), { replace: true })
        return info
      }
      const prefix = context ? `${context}：` : ''
      const text = `${prefix}${info.message}${info.hint ? `。${info.hint}` : ''}`
      if (info.action === 'verify') message.warning(text, 6)
      else message.error(text, 5)
      return info
    },
    [forget, location.pathname, location.search, message, navigate],
  )
}

/** 查询失败的页面级提示；会话失效时直接跳转登录页。 */
export function QueryFailure({ error, onRetry, title = '加载失败' }: { error: unknown; onRetry?: () => void; title?: string }) {
  const location = useLocation()
  const info = describeError(error)
  if (info.action === 'relogin') return <RedirectToLogin from={location.pathname + location.search} />
  return (
    <Alert
      type="error"
      showIcon
      title={title}
      description={<ErrorText info={info} />}
      action={onRetry && <Button size="small" onClick={onRetry}>重试</Button>}
    />
  )
}

export function ErrorText({ info }: { info: ErrorDescription }): ReactNode {
  return (
    <>
      {info.message}
      {info.hint && `。${info.hint}`}
      {info.requestId && <div className="request-id">请求编号：{info.requestId}</div>}
    </>
  )
}

function RedirectToLogin({ from }: { from: string }) {
  const forget = useForgetAdmin()
  useEffect(() => forget(), [forget])
  return <Navigate to={loginUrl(from)} replace />
}

/** 需要主办方会话的页面外壳：刷新后经 /auth/me 恢复会话与 CSRF。 */
export function AdminGuard() {
  const location = useLocation()
  const session = useSessionQuery()
  if (session.isPending) return <Spin className="page-spin" size="large" />
  if (session.isSuccess && !session.data) return <Navigate to={loginUrl(location.pathname + location.search)} replace />
  if (session.isError) {
    const info = describeError(session.error)
    if (info.action === 'relogin') return <RedirectToLogin from={location.pathname + location.search} />
    return (
      <Result
        status="error"
        title="无法确认登录状态"
        subTitle={<ErrorText info={info} />}
        extra={<Button onClick={() => void session.refetch()}>重试</Button>}
      />
    )
  }
  return (
    <SessionContext.Provider value={session.data!}>
      <Outlet />
    </SessionContext.Provider>
  )
}
