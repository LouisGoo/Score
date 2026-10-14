import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiError, mockApi, renderRoute } from '../test/render'
import { screenSnapshot, screenToken } from './test-fixtures'

vi.mock('antd', async importOriginal => ({ ...await importOriginal<typeof import('antd')>(),
  QRCode: ({ value }: { value: string }) => <div data-testid="public-qr" data-value={value} />,
}))
const clients: QueryClient[] = []
function render(token: string | null = screenToken) {
  window.history.replaceState(null, '', `/screen/g1${token ? `#token=${token}` : ''}`)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  clients.push(client)
  return renderRoute('/screen/g1', client)
}
beforeEach(() => window.history.replaceState(null, '', '/'))
afterEach(() => { clients.splice(0).forEach(c => c.clear()); vi.unstubAllGlobals() })

describe('independent screen', () => {
  it('clears the fragment and uses only the grant bearer, never a session or query-string token', async () => {
    const calls = mockApi({ 'GET /screens/g1/snapshot': { body: screenSnapshot() } })
    const { queryClient } = render()
    await screen.findByText('等待主持人开评')
    expect(window.location.hash).toBe('')
    expect(calls).toHaveLength(1)
    expect(calls[0]).toMatchObject({ method: 'GET', path: '/screens/g1/snapshot', query: '', headers: { Authorization: `Bearer ${screenToken}` } })
    expect(JSON.stringify(queryClient.getQueryCache().getAll().map(q => ({ key: q.queryKey, data: q.state.data })))).not.toContain(screenToken)
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })

  it.each([null, 'invalid'])('does not request snapshots without valid token syntax (%s)', async token => {
    const calls = mockApi({})
    render(token)
    await screen.findByText('请使用完整的大屏链接')
    expect(calls).toHaveLength(0)
    expect(window.location.hash).toBe('')
  })

  it.each([
    ['waiting', '等待主持人开评'], ['progress', '正在评分 · 001'], ['paused', '评分已暂停 · 001'],
    ['result', '成绩已公布 · 001'], ['leaderboard', '排行榜'], ['ended', '活动已结束'],
  ] as const)('renders %s without management controls or personal scores', async (mode, text) => {
    mockApi({ 'GET /screens/g1/snapshot': { body: { ...screenSnapshot(mode), secret: 'PRIVATE-JUDGE-CODE', ballots: [{ total: 'secret-score' }] } } })
    render()
    await screen.findByText(text)
    expect(screen.queryByText('PRIVATE-JUDGE-CODE')).not.toBeInTheDocument()
    expect(screen.queryByText('secret-score')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /开评|收评|公布|结束活动|撤销|修改评分/ })).not.toBeInTheDocument()
    if (mode === 'progress') expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '3')
    if (mode === 'paused') expect(screen.getByText('01:15')).toBeInTheDocument()
    if (mode === 'result') expect(screen.getByText('去最高最低后平均')).toBeInTheDocument()
  })

  it('renders only published entries and preserves authoritative tied ranks', async () => {
    const data = screenSnapshot('leaderboard')
    data.published_results.push({ ...data.published_results[0], entry_id: 'en2', round_id: 'r2', number: '002', name: '绿色出行' })
    data.ranking.push({ entry_id: 'en2', number: '002', name: '绿色出行', final_score: '90.50', rank: 1 },
      { entry_id: 'secret', number: '003', name: '未公布项目', final_score: '99.00', rank: 3 })
    mockApi({ 'GET /screens/g1/snapshot': { body: data } })
    render(); await screen.findByText('排行榜')
    expect(screen.getAllByRole('cell', { name: '1' })).toHaveLength(2)
    expect(screen.queryByText('未公布项目')).not.toBeInTheDocument()
  })

  it('does not render an unannounced result even if a round has a score-like field', async () => {
    const data = screenSnapshot('result'); data.published_results = []; data.current_round!.status = 'CLOSED'
    mockApi({ 'GET /screens/g1/snapshot': { body: data } })
    render(); await screen.findByText('成绩尚未公布')
    expect(screen.queryByText('90.50')).not.toBeInTheDocument()
  })

  it('enlarges only the public join URL and hides the QR when disabled remotely', async () => {
    const data = screenSnapshot()
    mockApi({ 'GET /screens/g1/snapshot': () => ({ body: data }) })
    const { queryClient } = render()
    await userEvent.click(await screen.findByRole('button', { name: '放大公共加入二维码' }))
    await screen.findByRole('dialog', { name: '扫码加入活动' })
    for (const qr of screen.getAllByTestId('public-qr')) {
      expect(qr).toHaveAttribute('data-value', 'http://localhost:3000/join/ABCDEFGH2345')
      expect(qr.getAttribute('data-value')).not.toContain(screenToken)
    }
    data.display.show_public_qr = false; data.version++
    await act(async () => { await queryClient.invalidateQueries({ queryKey: ['screen'] }) })
    await waitFor(() => expect(screen.queryByTestId('public-qr')).not.toBeInTheDocument())
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('retains the last confirmed display on outage, respects backoff, then recovers', async () => {
    const calls = mockApi({ 'GET /screens/g1/snapshot': [{ body: screenSnapshot('result') },
      { ...apiError('SERVICE_UNAVAILABLE', 503), headers: { 'Retry-After': '60' } }, { body: screenSnapshot('ended') }] })
    const { queryClient } = render(); await screen.findByText('90.50')
    await userEvent.click(screen.getByRole('button', { name: '重新同步' }))
    await screen.findByText(/连接中，数据可能延迟/)
    expect(screen.getByText('90.50')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '稍后重试' })).toBeDisabled()
    await act(async () => { await queryClient.invalidateQueries({ queryKey: ['screen'] }) })
    await screen.findByText('活动已结束')
    expect(calls.filter(c => c.method !== 'GET')).toHaveLength(0)
  })

  it('clears both the old display and query cache after grant revocation', async () => {
    mockApi({ 'GET /screens/g1/snapshot': [{ body: screenSnapshot('result') }, apiError('SCREEN_GRANT_INVALID', 401)] })
    const { queryClient } = render(); await screen.findByText('90.50')
    await userEvent.click(screen.getByRole('button', { name: '重新同步' }))
    await screen.findByText('大屏授权已失效')
    expect(screen.queryByText('90.50')).not.toBeInTheDocument()
    await waitFor(() => expect(queryClient.getQueriesData({ queryKey: ['screen'] })).toEqual([]))
  })

  it('ignores late snapshots with older versions', async () => {
    const old = screenSnapshot(); old.version = 4
    mockApi({ 'GET /screens/g1/snapshot': [{ body: screenSnapshot('result') }, { body: old }] })
    render(); await screen.findByText('90.50')
    await userEvent.click(screen.getByRole('button', { name: '重新同步' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '重新同步' })).toBeEnabled())
    expect(screen.getByText('90.50')).toBeInTheDocument()
    expect(screen.queryByText('等待主持人开评')).not.toBeInTheDocument()
  })

  it('gracefully explains when fullscreen is unavailable', async () => {
    mockApi({ 'GET /screens/g1/snapshot': { body: screenSnapshot() } })
    render(); await userEvent.click(await screen.findByRole('button', { name: '全屏显示' }))
    expect(await screen.findByText(/此浏览器不支持网页全屏/)).toBeInTheDocument()
  })
})
