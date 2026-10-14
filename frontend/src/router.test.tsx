import { screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { apiError, mockApi, renderRoute } from './test/render'

const session = { admin: { id: 'a1', login: 'host.admin' }, expires_at: '2026-10-14T08:00:00Z', csrf_token: 'csrf' }

function renderAt(path: string, signedIn = true) {
  mockApi({
    'GET /health/live': { body: { status: 'ok' } },
    'GET /auth/me': signedIn ? { body: session } : apiError('SESSION_EXPIRED', 401),
  })
  return renderRoute(path)
}

describe('routes', () => {
  it('renders the home page with service status', async () => {
    renderAt('/')
    expect(await screen.findByText('服务已连接')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '主办方登录' })).toHaveAttribute('href', '/admin/login')
  })

  it.each([
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
    const { router } = renderAt('/admin')
    await waitFor(() => expect(router.state.location.pathname).toBe('/admin/events'))
  })

  it('sends signed-out organizers to login with a return path', async () => {
    const { router } = renderAt('/admin/events/e1/control', false)
    expect(await screen.findByRole('button', { name: '登录' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/admin/login')
    expect(router.state.location.search).toBe('?next=%2Fadmin%2Fevents%2Fe1%2Fcontrol')
  })

  it('shows not found for unknown paths', async () => {
    renderAt('/nope')
    expect(await screen.findByText('页面不存在')).toBeInTheDocument()
  })
})
