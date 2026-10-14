import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient } from '@tanstack/react-query'
import { ApiError } from '../api/client'
import { judgeAuth, judgeScoring } from '../api/judge'
import { draftKey, loadDraft, saveDraft } from '../lib/drafts'
import { apiError, mockApi, renderRoute } from '../test/render'
import { ballotReceipt, judgeSession, judgeSnapshot, previewInfo } from './test-fixtures'
import { pendingSubmissions, saveSubmission } from './storage'

const scope = { eventId: 'e1', judgeId: 'j1', roundId: 'r1', ruleVersion: 1 }
const key = '12345678-1234-4234-8234-123456789abc'
const confirmation = { judge: judgeSession.judge, confirmation_token: 'confirm-token', expires_at: '2099-01-01T00:00:00Z' }
const clients: QueryClient[] = []
function render(path = '/judge/events/e1') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  clients.push(client)
  return renderRoute(path, client)
}
beforeEach(() => { judgeAuth.forget(); window.history.replaceState(null, '', '/'); vi.stubGlobal('navigator', navigator) })
afterEach(() => { clients.splice(0).forEach(c => c.clear()); vi.unstubAllGlobals() })

async function fill(values = ['90', '8', '18']) {
  for (const [i, name] of ['内容质量', '表达能力', '创新价值'].entries()) {
    fireEvent.change(await screen.findByLabelText(name), { target: { value: values[i] } })
  }
}
async function confirmScore() {
  await userEvent.click(screen.getByRole('button', { name: '核对并提交' }))
  const dialog = await screen.findByRole('dialog', { name: '确认本次评分' })
  await userEvent.click(within(dialog).getByRole('button', { name: '确认提交' }))
}

describe('joining and identity', () => {
  it('accepts an activity code and requires explicit identity confirmation before exchange', async () => {
    const calls = mockApi({
      'GET /judge-sessions/me': apiError('SESSION_EXPIRED', 401),
      'GET /join/ABCDEFGH2345': { body: previewInfo },
      'GET /judge-sessions/csrf': { body: { csrf_token: 'bootstrap' } },
      'POST /judge-sessions/verify': { body: confirmation },
      'POST /judge-sessions/exchange': { body: judgeSession },
      'GET /judge/events/e1/snapshot': { body: judgeSnapshot() },
    })
    const { router } = render('/join')
    await userEvent.type(await screen.findByLabelText('活动码'), 'abcdefgh2345')
    await userEvent.click(screen.getByRole('button', { name: '查看活动' }))
    await userEvent.type(await screen.findByLabelText('个人身份码'), 'PRIVATE-CODE')
    await userEvent.click(screen.getByRole('button', { name: '验证身份' }))
    expect(await screen.findByText('姓名：陈评委')).toBeInTheDocument()
    expect(calls.some(c => c.path.endsWith('/exchange'))).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: '确认是我，加入活动' }))
    await screen.findByLabelText('内容质量')
    expect(router.state.location.pathname).toBe('/judge/events/e1')
    expect(calls.find(c => c.path.endsWith('/exchange'))?.headers['X-CSRF-Token']).toBe('bootstrap')
    expect(JSON.stringify(localStorage)).not.toContain('PRIVATE-CODE')
  })

  it('clears private invitation fragments and verifies once without auto exchanging', async () => {
    window.history.replaceState(null, '', '/join/ABCDEFGH2345#code=PRIVATE')
    const calls = mockApi({
      'GET /judge-sessions/me': apiError('SESSION_EXPIRED', 401), 'GET /join/ABCDEFGH2345': { body: previewInfo },
      'GET /judge-sessions/csrf': { body: { csrf_token: 'bootstrap' } }, 'POST /judge-sessions/verify': { body: confirmation },
    })
    render('/join/ABCDEFGH2345')
    await screen.findByText('姓名：陈评委')
    expect(window.location.hash).toBe('')
    expect(calls.filter(c => c.path.endsWith('/verify'))).toHaveLength(1)
    expect(calls.some(c => c.path.endsWith('/exchange'))).toBe(false)
  })

  it('recovers a lost exchange response using me', async () => {
    mockApi({
      'GET /judge-sessions/me': [apiError('SESSION_EXPIRED', 401), { body: judgeSession }],
      'GET /join/ABCDEFGH2345': { body: previewInfo }, 'GET /judge-sessions/csrf': { body: { csrf_token: 'bootstrap' } },
      'POST /judge-sessions/verify': { body: confirmation },
      'POST /judge-sessions/exchange': () => { throw new Error('connection lost') },
      'GET /judge/events/e1/snapshot': { body: judgeSnapshot() },
    })
    render('/join/ABCDEFGH2345')
    await userEvent.type(await screen.findByLabelText('个人身份码'), 'private')
    await userEvent.click(screen.getByRole('button', { name: '验证身份' }))
    await userEvent.click(await screen.findByRole('button', { name: '确认是我，加入活动' }))
    expect(await screen.findByLabelText('内容质量')).toBeInTheDocument()
  })
})

describe('scoring, recovery and mobile states', () => {
  it('keeps empty scores distinct from zero and submits decimal strings after review', async () => {
    const snapshot = judgeSnapshot()
    const zero = ballotReceipt({ total_score: '0.00', scores: snapshot.rule.criteria.map(c => ({ criterion_id: c.criterion_id, value: '0' })) })
    const calls = mockApi({ 'GET /judge-sessions/me': { body: judgeSession }, 'GET /judge/events/e1/snapshot': () => ({ body: snapshot }),
      'PUT /rounds/r1/my-ballot': () => { snapshot.my_ballots = [{ judge_id: 'j1', receipts: [zero] }]; snapshot.version++; return { body: zero } },
    })
    render()
    expect(await screen.findByLabelText('内容质量')).toHaveValue('')
    await userEvent.click(screen.getByRole('button', { name: '核对并提交' }))
    expect(screen.getAllByText('请填写分数')).toHaveLength(3)
    expect(calls.some(c => c.method === 'PUT')).toBe(false)
    await fill(['0', '0', '0'])
    await confirmScore()
    expect(await screen.findByText('评分已保存')).toBeInTheDocument()
    const put = calls.find(c => c.method === 'PUT')!
    expect(put.body).toEqual({ rule_version: 1, expected_ballot_revision: 0, scores: zero.scores })
    expect(put.headers['Idempotency-Key']).toMatch(/^[a-f0-9-]{36}$/)
    expect(put.headers['X-CSRF-Token']).toBe('judge-csrf')
    expect(pendingSubmissions('e1', 'j1')).toEqual([])
  })

  it('previews 87.00 and rejects range and step errors', async () => {
    mockApi({ 'GET /judge-sessions/me': { body: judgeSession }, 'GET /judge/events/e1/snapshot': { body: judgeSnapshot() } })
    render()
    await fill()
    expect(screen.getByText('87.00')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('内容质量'), { target: { value: '101' } })
    expect(screen.getByText('不能超过满分 100')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('表达能力'), { target: { value: '1.05' } })
    expect(screen.getByText('须为 0.1 的整数倍')).toBeInTheDocument()
    expect(screen.getByText('待填写')).toBeInTheDocument()
  })

  it('saves the immutable request before PUT and verifies a lost response by the same key', async () => {
    const snapshot = judgeSnapshot()
    let sentKey = ''
    const calls = mockApi({ 'GET /judge-sessions/me': { body: judgeSession }, 'GET /judge/events/e1/snapshot': { body: snapshot },
      'PUT /rounds/r1/my-ballot': call => {
        sentKey = call.headers['Idempotency-Key']
        expect(pendingSubmissions('e1', 'j1')[0]).toMatchObject({ key: sentKey, body: call.body })
        throw new Error('lost response')
      },
      'GET /rounds/r1/my-ballot': { body: ballotReceipt() },
    })
    render(); await fill(); await confirmScore()
    await screen.findByText('评分已保存')
    expect(calls.find(c => c.method === 'GET' && c.path.endsWith('my-ballot'))?.headers['Idempotency-Key']).toBe(sentKey)
    expect(calls.filter(c => c.method === 'PUT')).toHaveLength(1)
  })

  it('does not show success without a receipt and retries with the original key and body', async () => {
    let attempts = 0
    const calls = mockApi({ 'GET /judge-sessions/me': { body: judgeSession }, 'GET /judge/events/e1/snapshot': { body: judgeSnapshot() },
      'PUT /rounds/r1/my-ballot': () => { if (++attempts === 1) throw new Error('offline'); return { body: ballotReceipt() } },
      'GET /rounds/r1/my-ballot': apiError('RECEIPT_NOT_FOUND', 404),
    })
    render(); await fill(); await confirmScore()
    await screen.findByText('正在核验提交结果')
    expect(screen.queryByText('评分已保存')).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: '使用原提交重试' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: '使用原提交重试' }))
    await screen.findByText('评分已保存')
    const puts = calls.filter(c => c.method === 'PUT')
    expect(puts).toHaveLength(2)
    expect(puts[1].body).toEqual(puts[0].body)
    expect(puts[1].headers['Idempotency-Key']).toBe(puts[0].headers['Idempotency-Key'])
  })

  it('recovers a persisted old-round submission after refresh without submitting it to the new round', async () => {
    const snapshot = judgeSnapshot()
    snapshot.rounds[0].status = 'CLOSED'; snapshot.rounds[1].status = 'OPEN'
    saveSubmission({ scope, key, body: { rule_version: 1, expected_ballot_revision: 0, scores: ballotReceipt().scores } })
    const calls = mockApi({ 'GET /judge-sessions/me': { body: judgeSession }, 'GET /judge/events/e1/snapshot': { body: snapshot },
      'GET /rounds/r1/my-ballot': apiError('RECEIPT_NOT_FOUND', 404) })
    render()
    await screen.findByText('正在核验提交结果')
    await waitFor(() => expect(calls.some(c => c.path === '/rounds/r1/my-ballot')).toBe(true))
    expect(calls.some(c => c.method === 'PUT')).toBe(false)
    expect(calls.some(c => c.path === '/rounds/r2/my-ballot')).toBe(false)
  })

  it('isolates drafts and closes the confirmation when a different object opens', async () => {
    const snapshot = judgeSnapshot()
    mockApi({ 'GET /judge-sessions/me': { body: judgeSession }, 'GET /judge/events/e1/snapshot': () => ({ body: snapshot }) })
    render(); await fill()
    await userEvent.click(screen.getByRole('button', { name: '核对并提交' }))
    await screen.findByRole('dialog')
    snapshot.version++; snapshot.rounds[0].status = 'CLOSED'; snapshot.rounds[1].status = 'OPEN'
    await act(async () => { await clients[0].invalidateQueries({ queryKey: ['judge', 'j1', 'snapshot', 'e1'] }) })
    await waitFor(() => expect(screen.getByLabelText('内容质量')).toHaveValue(''))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(loadDraft(scope)).toEqual({ a: '90', b: '8', c: '18' })
    expect(await screen.findByText('评分对象已切换，旧对象草稿已保留，不会带入新对象')).toBeInTheDocument()
  })

  it.each(['PAUSED', 'expired'] as const)('blocks submission when %s', async state => {
    const snapshot = judgeSnapshot()
    if (state === 'PAUSED') { snapshot.rounds[0].status = 'PAUSED'; snapshot.rounds[0].remaining_seconds = '60' }
    else snapshot.rounds[0].deadline_at = '2000-01-01T00:00:00Z'
    saveDraft(scope, { a: '90', b: '8', c: '18' })
    mockApi({ 'GET /judge-sessions/me': { body: judgeSession }, 'GET /judge/events/e1/snapshot': { body: snapshot } })
    render()
    expect(await screen.findByRole('button', { name: '核对并提交' })).toBeDisabled()
    expect(loadDraft(scope)?.a).toBe('90')
  })

  it('uses the latest revision for explicit revisions and keeps server history', async () => {
    const snapshot = judgeSnapshot()
    snapshot.my_ballots = [{ judge_id: 'j1', receipts: [ballotReceipt()] }]
    const calls = mockApi({ 'GET /judge-sessions/me': { body: judgeSession }, 'GET /judge/events/e1/snapshot': () => ({ body: snapshot }),
      'PUT /rounds/r1/my-ballot': call => {
        const next = ballotReceipt({ revision: 2, receipt_id: 'receipt-2', scores: (call.body as { scores: ReturnType<typeof ballotReceipt>['scores'] }).scores, total_score: '88.00' })
        snapshot.my_ballots[0].receipts.push(next); snapshot.version++
        return { body: next }
      } })
    render()
    await userEvent.click(await screen.findByRole('button', { name: '修改评分' }))
    fireEvent.change(screen.getByLabelText('内容质量'), { target: { value: '92' } })
    await confirmScore()
    await screen.findByText(/回执号：/)
    expect(calls.find(c => c.method === 'PUT')?.body).toMatchObject({ expected_ballot_revision: 1 })
    await userEvent.click(screen.getByRole('link', { name: '本人记录' }))
    expect(await screen.findByText('查看此前 1 个版本')).toBeInTheDocument()
    expect(screen.getByText('receipt-2')).toBeInTheDocument()
  })

  it('preserves the draft after a revision conflict and refreshes the server receipt', async () => {
    const snapshot = judgeSnapshot()
    const calls = mockApi({ 'GET /judge-sessions/me': { body: judgeSession }, 'GET /judge/events/e1/snapshot': () => ({ body: snapshot }),
      'PUT /rounds/r1/my-ballot': () => { snapshot.my_ballots = [{ judge_id: 'j1', receipts: [ballotReceipt()] }]; snapshot.version++; return apiError('REVISION_CONFLICT', 409) } })
    render(); await fill(); await confirmScore()
    await screen.findByText('服务端：REVISION_CONFLICT')
    expect(pendingSubmissions('e1', 'j1')).toEqual([])
    expect(loadDraft(scope)?.a).toBe('90')
    expect(calls.filter(c => c.method === 'PUT')).toHaveLength(1)
  })

  it('clears only the current identity storage and returns to join when revoked', async () => {
    saveDraft(scope, { a: '9' })
    saveDraft({ ...scope, judgeId: 'j2' }, { a: '8' })
    const snapshot = judgeSnapshot()
    mockApi({ 'GET /judge-sessions/me': { body: judgeSession }, 'GET /judge/events/e1/snapshot': [{ body: snapshot }, apiError('SESSION_EXPIRED', 401)],
      'GET /join/ABCDEFGH2345': { body: previewInfo } })
    const { router } = render()
    await userEvent.click(await screen.findByRole('button', { name: '同步状态' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/join/ABCDEFGH2345'))
    expect(localStorage.getItem(draftKey(scope))).toBeNull()
    expect(loadDraft({ ...scope, judgeId: 'j2' })).toEqual({ a: '8' })
  })

  it('does not send a ballot when durable submission storage is unavailable', async () => {
    mockApi({ 'GET /judge-sessions/me': { body: judgeSession }, 'GET /judge/events/e1/snapshot': { body: judgeSnapshot() } })
    const submit = vi.spyOn(judgeScoring, 'submit')
    render(); await fill()
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
    await confirmScore()
    expect(await screen.findByText(/浏览器无法保存提交记录/)).toBeInTheDocument()
    expect(submit).not.toHaveBeenCalled()
  })

  it('recovers a timeout using the precise key, never accepts a different latest receipt', async () => {
    vi.spyOn(judgeScoring, 'submit').mockRejectedValue(new ApiError(0, 'TIMEOUT', '请求超时'))
    const read = vi.spyOn(judgeScoring, 'receipt').mockRejectedValue(new ApiError(404, 'RECEIPT_NOT_FOUND', '尚未查到'))
    mockApi({ 'GET /judge-sessions/me': { body: judgeSession }, 'GET /judge/events/e1/snapshot': { body: judgeSnapshot() } })
    render(); await fill(); await confirmScore()
    await waitFor(() => expect(read).toHaveBeenCalledWith('r1', pendingSubmissions('e1', 'j1')[0].key))
    expect(screen.queryByText('评分已保存')).not.toBeInTheDocument()
  })

  it('does not refresh CSRF and replay a ballot under a different judge identity', async () => {
    const calls = mockApi({
      'GET /judge-sessions/me': [{ body: judgeSession }, { body: { ...judgeSession, judge: { ...judgeSession.judge, id: 'j2' } } }],
      'GET /judge/events/e1/snapshot': { body: judgeSnapshot() },
      'PUT /rounds/r1/my-ballot': apiError('CSRF_INVALID', 403),
      'GET /join/ABCDEFGH2345': { body: previewInfo },
    })
    const { router } = render(); await fill(); await confirmScore()
    await waitFor(() => expect(router.state.location.pathname).toBe('/join/ABCDEFGH2345'))
    expect(calls.filter(c => c.method === 'PUT')).toHaveLength(1)
  })

  it('refuses a snapshot for a different identity instead of carrying the draft across', async () => {
    const snapshot = judgeSnapshot(); snapshot.identity.id = 'j2'
    saveDraft(scope, { a: '90' })
    mockApi({ 'GET /judge-sessions/me': { body: judgeSession }, 'GET /judge/events/e1/snapshot': { body: snapshot } })
    const { router } = render()
    await waitFor(() => expect(router.state.location.pathname).toBe('/join'))
    expect(screen.queryByLabelText('内容质量')).not.toBeInTheDocument()
    expect(loadDraft(scope)).toBeNull()
  })

  it('honors Retry-After without immediately querying or resending', async () => {
    const calls = mockApi({ 'GET /judge-sessions/me': { body: judgeSession }, 'GET /judge/events/e1/snapshot': { body: judgeSnapshot() },
      'PUT /rounds/r1/my-ballot': { ...apiError('SERVICE_UNAVAILABLE', 503), headers: { 'Retry-After': '60' } } })
    render(); await fill(); await confirmScore()
    await screen.findByText('正在核验提交结果')
    expect(screen.getByRole('button', { name: '使用原提交重试' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '核验提交结果' })).toBeDisabled()
    expect(calls.filter(c => c.path.endsWith('my-ballot'))).toHaveLength(1)
  })

  it('does not automatically submit on reconnection and preserves the draft', async () => {
    const calls = mockApi({ 'GET /judge-sessions/me': { body: judgeSession }, 'GET /judge/events/e1/snapshot': { body: judgeSnapshot() } })
    render(); await fill()
    const online = vi.spyOn(navigator, 'onLine', 'get')
    online.mockReturnValue(false)
    act(() => { window.dispatchEvent(new Event('offline')) })
    expect(screen.getByRole('button', { name: '核对并提交' })).toBeDisabled()
    online.mockReturnValue(true)
    act(() => { window.dispatchEvent(new Event('online')) })
    await waitFor(() => expect(screen.getByRole('button', { name: '核对并提交' })).toBeEnabled())
    expect(calls.some(c => c.method === 'PUT')).toBe(false)
    expect(loadDraft(scope)).toEqual({ a: '90', b: '8', c: '18' })
  })

  it('does not overwrite another tab pending submission at confirmation', async () => {
    const calls = mockApi({ 'GET /judge-sessions/me': { body: judgeSession }, 'GET /judge/events/e1/snapshot': { body: judgeSnapshot() },
      'GET /rounds/r1/my-ballot': apiError('RECEIPT_NOT_FOUND', 404) })
    render(); await fill()
    await userEvent.click(screen.getByRole('button', { name: '核对并提交' }))
    const dialog = await screen.findByRole('dialog')
    saveSubmission({ scope, key, body: { rule_version: 1, expected_ballot_revision: 0, scores: ballotReceipt().scores } })
    await userEvent.click(within(dialog).getByRole('button', { name: '确认提交' }))
    await screen.findByText('正在核验提交结果')
    expect(calls.some(c => c.method === 'PUT')).toBe(false)
    expect(pendingSubmissions('e1', 'j1')[0].key).toBe(key)
  })

  it('sends only once when confirmation is double clicked', async () => {
    let resolve!: (receipt: ReturnType<typeof ballotReceipt>) => void
    const submit = vi.spyOn(judgeScoring, 'submit').mockImplementation(() => new Promise(done => { resolve = done }))
    mockApi({ 'GET /judge-sessions/me': { body: judgeSession }, 'GET /judge/events/e1/snapshot': { body: judgeSnapshot() } })
    render(); await fill()
    await userEvent.click(screen.getByRole('button', { name: '核对并提交' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.dblClick(within(dialog).getByRole('button', { name: '确认提交' }))
    expect(submit).toHaveBeenCalledTimes(1)
    await act(async () => resolve(ballotReceipt()))
    await screen.findByText('评分已保存')
  })

  it('logs out with confirmation, clears drafts, and returns to this activity', async () => {
    const calls = mockApi({ 'GET /judge-sessions/me': { body: judgeSession }, 'GET /judge/events/e1/snapshot': { body: judgeSnapshot() },
      'POST /judge-sessions/logout': { status: 204 }, 'GET /join/ABCDEFGH2345': { body: previewInfo } })
    const { router } = render(); await fill()
    await userEvent.click(screen.getByRole('button', { name: '退出身份' }))
    expect(calls.some(c => c.path.endsWith('/logout'))).toBe(false)
    await userEvent.click(await screen.findByRole('button', { name: '确认退出' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/join/ABCDEFGH2345'))
    expect(await screen.findByLabelText('个人身份码')).toBeInTheDocument()
    expect(loadDraft(scope)).toBeNull()
  })
})
