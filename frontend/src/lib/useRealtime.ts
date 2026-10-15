import { useEffect, useRef, useState } from 'react'
import { useQueryClient, type QueryKey } from '@tanstack/react-query'
import { ApiError, type Client } from '../api/client'
import { RealtimeSync, type SyncStatus, type Ticket } from './realtime'

interface Options {
  key: QueryKey
  role: 'admin' | 'judge' | 'screen'
  eventId?: string
  grantId?: string
  api: Client
  enabled?: boolean
  refetch(options?: { cancelRefetch?: boolean }): Promise<{ data?: { version: number }; error: unknown }>
}

export function useRealtime(options: Options) {
  const client = useQueryClient()
  const current = useRef(options)
  useEffect(() => { current.current = options })
  const identity = JSON.stringify(options.key)
  const [state, setState] = useState<{ identity: string; status: SyncStatus; verifiedAt: number; error: ApiError | null }>({
    identity, status: 'connecting', verifiedAt: 0, error: null,
  })
  useEffect(() => {
    if (!options.eventId || options.enabled === false) return
    let disposed = false
    const change = (patch: Partial<typeof state>) => {
      if (!disposed) setState(previous => ({ ...previous, identity, ...patch }))
    }
    change({ status: 'connecting', verifiedAt: 0, error: null })
    const body = { event_id: options.eventId, role: options.role, grant_id: options.grantId }
    const versionPath = '/realtime/version?' + new URLSearchParams({
      event_id: options.eventId, role: options.role, ...(options.grantId ? { grant_id: options.grantId } : {}),
    })
    const sync = new RealtimeSync({
      eventId: options.eventId, role: options.role,
      ticket: signal => current.current.api.send<Ticket>('POST', '/realtime/tickets', body, { signal }),
      version: async signal => (await current.current.api.get<{ version: number }>(versionPath, { signal })).version,
      currentVersion: () => client.getQueryData<{ version: number }>(current.current.key)?.version ?? -1,
      snapshot: async () => {
        const scope = current.current
        const previous = client.getQueryState(scope.key)
        if (previous?.error instanceof ApiError && previous.error.retryAfter) {
          const remaining = previous.errorUpdatedAt + previous.error.retryAfter * 1000 - Date.now()
          if (remaining > 0) throw new ApiError(previous.error.status, previous.error.code,
            previous.error.message, previous.error.requestId, Math.ceil(remaining / 1000))
        }
        // 不复用连接建立前启动的 HTTP 读视图；也不取消用户手动核验中的查询。
        if (previous?.fetchStatus === 'fetching') await scope.refetch({ cancelRefetch: false })
        if (disposed) throw new DOMException('Aborted', 'AbortError')
        const result = await scope.refetch({ cancelRefetch: false })
        if (result.error) throw result.error
        if (!result.data) throw new ApiError(0, 'NETWORK_ERROR', '暂时无法同步状态')
        return result.data.version
      },
      socket: path => {
        const url = new URL(path, window.location.href)
        if (url.origin !== window.location.origin) throw new Error('Invalid stream origin')
        url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
        return new WebSocket(url)
      },
      status: status => change({ status }),
      verified: () => change({ verifiedAt: Date.now() }),
      invalid: error => {
        change({ error, status: 'expired' })
        void client.cancelQueries({ queryKey: current.current.key })
        client.removeQueries({ queryKey: current.current.key })
      },
    })
    const foreground = () => {
      if (document.visibilityState === 'hidden') sync.pause('paused')
      else if (!navigator.onLine) sync.pause('offline')
      else sync.resume()
    }
    if (document.visibilityState === 'hidden') sync.pause('paused')
    else if (!navigator.onLine) sync.pause('offline')
    else sync.resume(false)
    document.addEventListener('visibilitychange', foreground)
    window.addEventListener('online', foreground)
    window.addEventListener('offline', foreground)
    window.addEventListener('focus', foreground)
    return () => {
      disposed = true
      sync.stop()
      document.removeEventListener('visibilitychange', foreground)
      window.removeEventListener('online', foreground)
      window.removeEventListener('offline', foreground)
      window.removeEventListener('focus', foreground)
    }
  }, [client, identity, options.eventId, options.role, options.grantId, options.enabled])
  return state.identity === identity ? state : { status: 'connecting' as const, verifiedAt: 0, error: null }
}

