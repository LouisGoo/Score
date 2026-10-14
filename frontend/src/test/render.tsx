import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { App as AntApp, ConfigProvider } from 'antd'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { vi } from 'vitest'
import { createQueryClient } from '../api/query'
import { routes } from '../router'

export interface Call {
  method: string
  path: string
  query: string
  headers: Record<string, string>
  body: unknown
}

type Reply = { status?: number; body?: unknown; headers?: Record<string, string> }
type Handler = Reply | ((call: Call) => Reply)

export const apiError = (code: string, status: number, extra: Record<string, unknown> = {}): Reply => ({
  status,
  body: { error: { code, message: `服务端：${code}`, ...extra }, request_id: 'r'.repeat(32) },
})

/**
 * 按“方法 路径”（不含 /api/v1 与查询串）分派预设响应；值为数组时依次取用，最后一个重复使用。
 * 未登记的请求返回 404，便于发现意外调用。
 */
export function mockApi(routesTable: Record<string, Handler | Handler[]>) {
  const calls: Call[] = []
  const queues = new Map(Object.entries(routesTable).map(([k, v]) => [k, Array.isArray(v) ? [...v] : [v]]))
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = new URL(String(input), 'http://localhost')
      const call: Call = {
        method: init.method ?? 'GET',
        path: url.pathname.replace(/^\/api\/v1/, ''),
        query: url.search,
        headers: (init.headers ?? {}) as Record<string, string>,
        body: init.body ? JSON.parse(String(init.body)) : undefined,
      }
      calls.push(call)
      const queue = queues.get(`${call.method} ${call.path}`)
      const handler = queue ? (queue.length > 1 ? queue.shift()! : queue[0]) : apiError('NOT_FOUND', 404)
      const reply = typeof handler === 'function' ? handler(call) : handler
      const status = reply.status ?? 200
      return new Response(status === 204 || reply.body === undefined ? null : JSON.stringify(reply.body), {
        status,
        headers: { 'Content-Type': 'application/json', 'X-Request-ID': 'r'.repeat(32), ...reply.headers },
      })
    }),
  )
  return calls
}

export function renderRoute(path: string, queryClient: QueryClient = createQueryClient()) {
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  const view = render(
    <ConfigProvider theme={{ token: { motion: false } }} button={{ autoInsertSpace: false }}>
      <AntApp>
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>,
  )
  return { router, queryClient, ...view }
}
