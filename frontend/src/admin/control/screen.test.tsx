import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient } from '@tanstack/react-query'
import { afterEach, describe, expect, it } from 'vitest'
import { apiError, mockApi, renderRoute } from '../../test/render'
import { adminScreenSnapshot, adminSession, screenToken } from '../../screen/test-fixtures'

const clients: QueryClient[] = []
function render() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  clients.push(client)
  return renderRoute('/admin/events/e1/control', client)
}
afterEach(() => clients.splice(0).forEach(c => c.clear()))
const grant = { id: 'g1', event_id: 'e1', created_at: '2026-10-14T12:00:00Z', expires_at: '2099-01-01T00:00:00Z', revoked_at: null }

describe('screen management in the console', () => {
  it('creates a one-time fragment link and keeps the token out of all query and mutation data', async () => {
    const data = adminScreenSnapshot()
    const calls = mockApi({ 'GET /auth/me': { body: adminSession }, 'GET /events/e1/snapshot': () => ({ body: data }),
      'POST /events/e1/screen-grants': () => { data.screen_grants.push(grant); return { body: { ...grant, token: screenToken }, status: 201 } } })
    const { queryClient } = render()
    await userEvent.click(await screen.findByRole('button', { name: '大屏管理' }))
    await userEvent.click(screen.getByRole('button', { name: '创建大屏链接' }))
    const link = await screen.findByRole('link', { name: '打开大屏' })
    expect(link.getAttribute('href')).toContain(`/screen/g1#token=${screenToken}`)
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    expect(calls.find(c => c.method === 'POST' && c.path.endsWith('/screen-grants'))).toMatchObject({ body: { ttl_seconds: 86400 }, headers: { 'X-CSRF-Token': 'admin-csrf' } })
    expect(JSON.stringify(queryClient.getQueryCache().getAll().map(q => q.state.data))).not.toContain(screenToken)
    expect(JSON.stringify(queryClient.getMutationCache().getAll().map(m => m.state.data))).not.toContain(screenToken)
    await userEvent.click(screen.getByRole('button', { name: '已保存，隐藏链接' }))
    expect(screen.queryByRole('link', { name: '打开大屏' })).not.toBeInTheDocument()
  })

  it('requires confirmation to revoke one grant and refreshes its state', async () => {
    const data = adminScreenSnapshot(); data.screen_grants = [grant]
    const calls = mockApi({ 'GET /auth/me': { body: adminSession }, 'GET /events/e1/snapshot': () => ({ body: data }),
      'DELETE /events/e1/screen-grants/g1': () => { data.screen_grants = [{ ...grant, revoked_at: new Date().toISOString() }]; return { status: 204 } } })
    render(); await userEvent.click(await screen.findByRole('button', { name: '大屏管理' }))
    await userEvent.click(screen.getByRole('button', { name: '撤销授权 g1' }))
    expect(calls.some(c => c.method === 'DELETE')).toBe(false)
    await userEvent.click(await screen.findByRole('button', { name: '确认撤销' }))
    await screen.findByText('已撤销')
    expect(calls.filter(c => c.method === 'DELETE')).toHaveLength(1)
  })

  it('saves display preferences with the captured event version', async () => {
    const data = adminScreenSnapshot()
    const calls = mockApi({ 'GET /auth/me': { body: adminSession }, 'GET /events/e1/snapshot': { body: data }, 'PUT /events/e1/screen': { body: data.display } })
    render(); await userEvent.click(await screen.findByRole('button', { name: '大屏管理' }))
    await userEvent.click(screen.getByRole('button', { name: '编辑展示设置' }))
    // Ant Design uses the same test-only title id for nested Drawer/Modal; locate its own dialog.
    const dialog = (await screen.findByText('编辑大屏展示')).closest('[role="dialog"]') as HTMLElement
    fireEvent.change(within(dialog).getByLabelText('大屏标题'), { target: { value: '年度成果展示' } })
    await userEvent.click(within(dialog).getByRole('switch'))
    await userEvent.click(within(dialog).getByRole('button', { name: '应用到大屏' }))
    await waitFor(() => expect(calls.some(c => c.method === 'PUT')).toBe(true))
    expect(calls.find(c => c.method === 'PUT')?.body).toMatchObject({ mode: 'progress', round_id: 'r1', expected_version: 5, title: '年度成果展示', show_public_qr: false })
  })

  it('closes a stale editor and refreshes after a version conflict without replay', async () => {
    const data = adminScreenSnapshot()
    const calls = mockApi({ 'GET /auth/me': { body: adminSession }, 'GET /events/e1/snapshot': { body: data }, 'PUT /events/e1/screen': apiError('VERSION_CONFLICT', 409) })
    render(); await userEvent.click(await screen.findByRole('button', { name: '大屏管理' }))
    await userEvent.click(screen.getByRole('button', { name: '编辑展示设置' }))
    await userEvent.click(await screen.findByRole('button', { name: '应用到大屏' }))
    await waitFor(() => expect(screen.queryByText('编辑大屏展示')).not.toBeInTheDocument())
    expect(calls.filter(c => c.method === 'PUT')).toHaveLength(1)
    expect(calls.filter(c => c.path === '/events/e1/snapshot').length).toBeGreaterThan(1)
  })

  it('does not auto-repeat grant creation when its response is lost', async () => {
    const data = adminScreenSnapshot()
    const calls = mockApi({ 'GET /auth/me': { body: adminSession }, 'GET /events/e1/snapshot': { body: data },
      'POST /events/e1/screen-grants': () => { throw new Error('lost response') } })
    render(); await userEvent.click(await screen.findByRole('button', { name: '大屏管理' }))
    await userEvent.click(screen.getByRole('button', { name: '创建大屏链接' }))
    await screen.findByText('操作结果待核对，请勿连续重试')
    expect(calls.filter(c => c.method === 'POST' && c.path.endsWith('/screen-grants'))).toHaveLength(1)
    expect(screen.queryByRole('link', { name: '打开大屏' })).not.toBeInTheDocument()
  })

  it('allows screen management after the event ends', async () => {
    const data = adminScreenSnapshot(); data.event.status = 'FINISHED'; data.rounds[0].status = 'PUBLISHED'; data.display.mode = 'ended'; data.display.round_id = null
    mockApi({ 'GET /auth/me': { body: adminSession }, 'GET /events/e1/snapshot': { body: data } })
    render(); await userEvent.click(await screen.findByRole('button', { name: '大屏管理' }))
    await userEvent.click(screen.getByRole('button', { name: '编辑展示设置' }))
    expect(await screen.findByText('编辑大屏展示')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '应用到大屏' })).toBeEnabled()
  })
})
