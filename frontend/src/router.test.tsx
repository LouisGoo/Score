import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { createQueryClient } from './api/query'
import { routes } from './router'

function renderAt(path: string) {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ status: 'ok' }), { status: 200 })))
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

describe('routes', () => {
  it('renders the home page with service status', async () => {
    renderAt('/')
    expect(await screen.findByText('服务已连接')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '主办方登录' })).toHaveAttribute('href', '/admin/login')
  })

  it.each([
    ['/admin/events', '活动列表', '14b'],
    ['/admin/events/e1/control', '主持人控制台', '15'],
    ['/join/ABCDEFGH2345', '加入活动', '16'],
    ['/judge/events/e1/history', '本人记录', '16'],
    ['/screen/g1', '现场大屏', '17'],
  ])('lazy-loads %s', async (path, title, batch) => {
    renderAt(path)
    expect(await screen.findByText(title)).toBeInTheDocument()
    expect(screen.getByText(`该页面将在 ${batch} 批次实现`)).toBeInTheDocument()
  })

  it('redirects /admin to the event list', async () => {
    const router = renderAt('/admin')
    expect(await screen.findByText('活动列表')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/admin/events')
  })

  it('shows not found for unknown paths', async () => {
    renderAt('/nope')
    expect(await screen.findByText('页面不存在')).toBeInTheDocument()
  })
})
