import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { EventInfo, EventListItem, JudgeInfo, PublishCheck } from '../api/types'
import { apiError, mockApi, renderRoute, type Call } from '../test/render'

const session = { admin: { id: 'a1', login: 'host.admin' }, expires_at: '2026-10-14T08:00:00Z', csrf_token: 'session-csrf' }

const draft: EventInfo = {
  id: 'e1',
  owner_id: 'a1',
  title: '联调项目评审',
  description: '',
  organization: '研发部',
  planned_at: null,
  scoring_rule: {
    mode: 'single',
    criteria: [{ criterion_id: 'total', name: '综合评分', maximum: '100', weight: '1', step: '0.1' }],
    algorithm: 'mean',
    minimum_ballots: null,
  },
  duration_seconds: 180,
  allow_revisions: true,
  screen_title: '',
  screen_theme: 'light',
  show_public_qr: true,
  leaderboard_limit: 10,
  status: 'DRAFT',
  public_code: null,
  published_at: null,
  version: 0,
  created_at: '2026-10-14T00:00:00Z',
  updated_at: '2026-10-14T00:00:00Z',
}

const published: EventInfo = { ...draft, status: 'READY', public_code: 'ABCDEFGH2345', published_at: '2026-10-14T01:00:00Z', version: 1 }

const judge: JudgeInfo = {
  id: 'j1',
  event_id: 'e1',
  number: '001',
  name: '评委甲',
  credential_is_set: false,
  credential_source: null,
  credential_version: 0,
  credential_updated_at: null,
}

const credential = (code: string) => ({
  event_id: 'e1',
  judge_id: 'j1',
  code,
  credential_source: 'generated' as const,
  credential_version: 1,
  credential_updated_at: '2026-10-14T01:00:00Z',
})

const check = (patch: Partial<PublishCheck> = {}): PublishCheck => ({
  can_publish: true,
  issues: [],
  entry_count: 1,
  judge_count: 1,
  missing_credential_count: 1,
  minimum_ballots: 1,
  ...patch,
})

/** 测试环境中 antd 弹窗的 aria-labelledby 均为固定的 test-id，按标题文本定位弹窗。 */
async function dialogTitled(title: string) {
  return (await screen.findByText(title, { selector: '.ant-modal-title' })).closest<HTMLElement>('[role="dialog"]')!
}

const writes = (calls: Call[]) => calls.filter(c => c.method !== 'GET')

/** 页面状态之外，查询缓存与变更缓存中都不应残留身份码明文。 */
function cachesContain(queryClient: import('@tanstack/react-query').QueryClient, text: string) {
  const queries = queryClient.getQueryCache().getAll().map(q => q.state.data)
  const mutations = queryClient.getMutationCache().getAll().map(m => m.state.data)
  return JSON.stringify([queries, mutations]).includes(text)
}

describe('organizer login', () => {
  it('logs in with the pre-login CSRF and returns to the requested page', async () => {
    const item: EventListItem = { ...published, status: 'RUNNING', entry_count: 3, judge_count: 5, round_count: 3, finished_round_count: 1 }
    const calls = mockApi({
      'GET /auth/me': apiError('SESSION_EXPIRED', 401),
      'GET /auth/csrf': { body: { csrf_token: 'pre-login' } },
      'POST /auth/login': { body: session },
      'GET /events': { body: [item] },
    })
    const user = userEvent.setup()
    const { router } = renderRoute('/admin/login?next=%2Fadmin%2Fevents')

    await user.type(await screen.findByLabelText('账号'), ' Host.Admin ')
    await user.type(screen.getByLabelText('密码'), 'secret')
    await user.click(screen.getByRole('button', { name: '登录' }))

    expect(await screen.findByText('联调项目评审')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/admin/events')
    const login = calls.find(c => c.path === '/auth/login')!
    expect(login.headers['X-CSRF-Token']).toBe('pre-login')
    expect(login.body).toEqual({ login: 'Host.Admin', password: 'secret' })
    expect(screen.getByText('1/3')).toBeInTheDocument()
    expect(screen.getByText('进行中')).toBeInTheDocument()
    expect(screen.getByText('host.admin')).toBeInTheDocument()
  })

  it('shows invalid credentials and clears the password', async () => {
    mockApi({
      'GET /auth/me': apiError('SESSION_EXPIRED', 401),
      'GET /auth/csrf': { body: { csrf_token: 'pre-login' } },
      'POST /auth/login': apiError('INVALID_CREDENTIALS', 401),
    })
    const user = userEvent.setup()
    renderRoute('/admin/login')
    await user.type(await screen.findByLabelText('账号'), 'host.admin')
    await user.type(screen.getByLabelText('密码'), 'wrong')
    await user.click(screen.getByRole('button', { name: '登录' }))
    expect(await screen.findByText('账号或密码不正确')).toBeInTheDocument()
    expect(screen.getByLabelText('密码')).toHaveValue('')
  })
})

describe('organizer logout', () => {
  it('clears the header identity and returns to login even if logout fails', async () => {
    const calls = mockApi({
      'GET /auth/me': { body: session },
      'GET /events': { body: [] },
      'POST /auth/logout': apiError('SERVICE_UNAVAILABLE', 503),
    })
    const user = userEvent.setup()
    const { router } = renderRoute('/admin/events')
    expect(await screen.findByText('host.admin')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /退出/ }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/admin/login'))
    expect(screen.queryByText('host.admin')).not.toBeInTheDocument()
    expect(await screen.findByRole('button', { name: '登录' })).toBeInTheDocument()
    expect(calls.find(c => c.path === '/auth/logout')!.headers['X-CSRF-Token']).toBe('session-csrf')
  })
})

describe('event create', () => {
  it('creates with the default rule and continues to the roster', async () => {
    const calls = mockApi({
      'GET /auth/me': { body: session },
      'POST /events': { status: 201, body: draft },
      'GET /events/e1': { body: draft },
      'GET /events/e1/judges': { body: [] },
      'GET /events/e1/entries': { body: [] },
    })
    const user = userEvent.setup()
    const { router } = renderRoute('/admin/events/new')
    await user.type(await screen.findByLabelText('活动名称'), '  联调项目评审 ')
    await user.click(screen.getByRole('button', { name: '创建并继续录入名单' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/admin/events/e1/settings'))
    expect(router.state.location.search).toBe('?tab=entries')
    expect(writes(calls)[0].body).toMatchObject({
      title: '联调项目评审',
      duration_seconds: 180,
      planned_at: null,
      scoring_rule: draft.scoring_rule,
    })
  })
})

describe('scoring rule editor', () => {
  it('blocks invalid weights and saves exact decimal weights', async () => {
    const calls = mockApi({
      'GET /auth/me': { body: session },
      'GET /events/e1': { body: draft },
      'GET /events/e1/judges': { body: [judge] },
      'PATCH /events/e1': { body: draft },
    })
    const user = userEvent.setup()
    renderRoute('/admin/events/e1/settings?tab=rule')
    await user.click(await screen.findByText('多维度加权'))
    await user.type(screen.getByLabelText('维度 2 名称'), '现场表现')
    await user.clear(screen.getByLabelText('维度 1 权重'))
    await user.type(screen.getByLabelText('维度 1 权重'), '60')
    await user.clear(screen.getByLabelText('维度 2 权重'))
    await user.type(screen.getByLabelText('维度 2 权重'), '30')
    expect(screen.getByText('权重合计 90%')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '保存评分规则' }))
    expect(await screen.findByText('权重合计须为 100%，当前为 90%')).toBeInTheDocument()
    expect(writes(calls)).toHaveLength(0)

    await user.clear(screen.getByLabelText('维度 2 权重'))
    await user.type(screen.getByLabelText('维度 2 权重'), '40')
    await user.click(screen.getByRole('button', { name: '保存评分规则' }))
    await waitFor(() => expect(writes(calls)).toHaveLength(1))
    expect(writes(calls)[0].body).toEqual({
      scoring_rule: {
        mode: 'multi',
        criteria: [
          { criterion_id: 'total', name: '综合评分', maximum: '100', weight: '0.6', step: '0.1' },
          { criterion_id: 'c2', name: '现场表现', maximum: '100', weight: '0.4', step: '0.1' },
        ],
        algorithm: 'mean',
        minimum_ballots: null,
      },
    })
  })
})

describe('event list', () => {
  it('shows draft summary and deletes only after confirmation', async () => {
    const item: EventListItem = { ...draft, entry_count: 2, judge_count: 0, round_count: 0, finished_round_count: 0 }
    const calls = mockApi({
      'GET /auth/me': { body: session },
      'GET /events': [{ body: [item] }, { body: [] }],
      'DELETE /events/e1': { status: 204 },
    })
    const user = userEvent.setup()
    renderRoute('/admin/events')
    const row = (await screen.findByText('联调项目评审')).closest('tr')!
    expect(within(row).getByText('未发布')).toBeInTheDocument()
    expect(within(row).queryByText('控制台')).not.toBeInTheDocument()

    await user.click(within(row).getByRole('button', { name: '删除' }))
    expect(writes(calls)).toHaveLength(0)
    const confirm = await screen.findByRole('dialog')
    await user.click(within(confirm).getByRole('button', { name: '删除' }))
    await waitFor(() => expect(writes(calls)).toEqual([expect.objectContaining({ method: 'DELETE', path: '/events/e1' })]))
    expect(writes(calls)[0].headers['X-CSRF-Token']).toBe('session-csrf')
    expect(await screen.findByText('还没有活动，点击“创建活动”开始')).toBeInTheDocument()
  })
})

describe('publish check and publish', () => {
  it('lists blocking issues with links to the right tab', async () => {
    mockApi({
      'GET /auth/me': { body: session },
      'GET /events/e1': { body: draft },
      'GET /events/e1/judges': { body: [judge] },
      'GET /events/e1/entries': { body: [] },
      'GET /events/e1/publish-check': {
        body: check({
          can_publish: false,
          entry_count: 0,
          issues: [{ code: 'ENTRIES_REQUIRED', message: '至少需要一个参评对象', field: 'entries' }],
        }),
      },
    })
    const user = userEvent.setup()
    const { router } = renderRoute('/admin/events/e1/settings?tab=publish')
    expect(await screen.findByText('至少需要一个参评对象')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '发布活动' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: '去“参评对象”' }))
    await waitFor(() => expect(router.state.location.search).toBe('?tab=entries'))
    expect(await screen.findByText('还没有参评对象，发布前至少需要一个')).toBeInTheDocument()
  })

  it('shows generated credentials once after publishing and keeps them out of caches', async () => {
    const calls = mockApi({
      'GET /auth/me': { body: session },
      'GET /events/e1': [{ body: draft }, { body: published }],
      'GET /events/e1/judges': { body: [judge] },
      'GET /events/e1/publish-check': { body: check() },
      'GET /events/e1/publication': { body: { event: published, snapshot: {}, rounds: [] } },
      'POST /events/e1/publish': {
        body: { event: published, snapshot: {}, rounds: [], generated_credentials: [credential('K7M2P9Q4R8T3')] },
      },
    })
    const user = userEvent.setup()
    const { queryClient } = renderRoute('/admin/events/e1/settings?tab=publish')
    await user.click(await screen.findByRole('button', { name: '发布活动' }))
    await user.click(await screen.findByRole('button', { name: '确认发布' }))

    const dialog = await dialogTitled('发布成功：自动生成的身份码')
    expect(within(dialog).getAllByText('K7M2P9Q4R8T3').length).toBeGreaterThan(0)
    expect(within(dialog).getByText('评委甲')).toBeInTheDocument()
    expect(within(dialog).getByText(/的私人邀请/)).toBeInTheDocument()
    expect(writes(calls).map(c => c.path)).toEqual(['/events/e1/publish'])
    expect(cachesContain(queryClient, 'K7M2P9Q4R8T3')).toBe(false)

    await user.click(within(dialog).getByRole('button', { name: '完成' }))
    await user.click(await screen.findByRole('button', { name: '已记录，关闭' }))
    await waitFor(() => expect(screen.queryByText('K7M2P9Q4R8T3')).not.toBeInTheDocument())
    expect(await screen.findByText('活动已发布，名单、评分规则与过程规则已冻结')).toBeInTheDocument()
    expect(screen.getByText('ABCDEFGH2345')).toBeInTheDocument()
  })

  it('verifies via the publication record instead of retrying when the outcome is unknown', async () => {
    const calls = mockApi({
      'GET /auth/me': { body: session },
      'GET /events/e1': [{ body: draft }, { body: published }],
      'GET /events/e1/judges': { body: [judge] },
      'GET /events/e1/publish-check': { body: check() },
      'GET /events/e1/publication': { body: { event: published, snapshot: {}, rounds: [] } },
      'POST /events/e1/publish': () => {
        throw new TypeError('Failed to fetch')
      },
    })
    const user = userEvent.setup()
    renderRoute('/admin/events/e1/settings?tab=publish')
    await user.click(await screen.findByRole('button', { name: '发布活动' }))
    await user.click(await screen.findByRole('button', { name: '确认发布' }))
    expect(await screen.findByText(/本次自动生成的身份码明文未能取回/)).toBeInTheDocument()
    expect(writes(calls).map(c => c.path)).toEqual(['/events/e1/publish'])
  })

  it('shows issues returned by a rejected publish', async () => {
    mockApi({
      'GET /auth/me': { body: session },
      'GET /events/e1': { body: draft },
      'GET /events/e1/judges': { body: [judge] },
      'GET /events/e1/publish-check': { body: check() },
      'POST /events/e1/publish': apiError('PUBLISH_INVALID', 422, {
        issues: [{ code: 'JUDGES_REQUIRED', message: '至少需要一位评委', field: 'judges' }],
      }),
    })
    const user = userEvent.setup()
    renderRoute('/admin/events/e1/settings?tab=publish')
    await user.click(await screen.findByRole('button', { name: '发布活动' }))
    await user.click(await screen.findByRole('button', { name: '确认发布' }))
    expect(await screen.findByText('至少需要一位评委')).toBeInTheDocument()
    expect(screen.getByText('发布被拒绝：配置不满足发布条件')).toBeInTheDocument()
  })
})

describe('judge credentials', () => {
  it('generates a draft credential and shows the plaintext only in the dialog', async () => {
    const calls = mockApi({
      'GET /auth/me': { body: session },
      'GET /events/e1': { body: draft },
      'GET /events/e1/judges': [{ body: [judge] }, { body: [{ ...judge, credential_is_set: true, credential_source: 'generated', credential_version: 1 }] }],
      'PUT /events/e1/judges/j1/credential': { body: credential('H3J4K5L6M7N8') },
    })
    const user = userEvent.setup()
    const { queryClient } = renderRoute('/admin/events/e1/settings?tab=judges')
    await user.click(await screen.findByRole('button', { name: '设置身份码' }))
    await user.click(await screen.findByRole('button', { name: '确定' }))

    const dialog = await dialogTitled('身份码已设置')
    expect(within(dialog).getAllByText('H3J4K5L6M7N8').length).toBeGreaterThan(0)
    expect(within(dialog).getByText(/暂不能生成私人邀请二维码/)).toBeInTheDocument()
    expect(writes(calls)[0].body).toEqual({ code: null })
    expect(cachesContain(queryClient, 'H3J4K5L6M7N8')).toBe(false)
    expect(await screen.findByText('已设置')).toBeInTheDocument()
  })

  it('requires a reason to reset after publishing', async () => {
    const calls = mockApi({
      'GET /auth/me': { body: session },
      'GET /events/e1': { body: published },
      'GET /events/e1/publication': { body: { event: published, snapshot: {}, rounds: [] } },
      'GET /events/e1/judges': { body: [{ ...judge, credential_is_set: true, credential_source: 'manual', credential_version: 1 }] },
      'POST /events/e1/judges/j1/reset-credential': { body: { ...credential('Q2W3E4R5T6Y7'), credential_version: 2 } },
    })
    const user = userEvent.setup()
    renderRoute('/admin/events/e1/settings?tab=judges')
    expect(await screen.findByText('活动已发布，名单、评分规则与过程规则已冻结')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '添加评委' })).not.toBeInTheDocument()

    await user.click(await screen.findByRole('button', { name: '重置身份码' }))
    await user.click(await screen.findByRole('button', { name: '确认重置' }))
    expect(await screen.findByText('请填写重置原因')).toBeInTheDocument()
    expect(writes(calls)).toHaveLength(0)

    await user.type(screen.getByLabelText('重置原因'), '更换手机')
    await user.click(screen.getByRole('button', { name: '确认重置' }))
    const dialog = await dialogTitled('新的身份码')
    expect(within(dialog).getByText(/的私人邀请/)).toBeInTheDocument()
    expect(writes(calls)[0].body).toEqual({ reason: '更换手机', code: null })
  })
})
