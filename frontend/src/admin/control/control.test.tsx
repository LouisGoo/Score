import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { adminExports } from '../../api/admin'
import { ApiError } from '../../api/client'
import * as downloads from '../../lib/download'
import { queryKeys } from '../../api/query'
import type { AdminSnapshot, EventInfo, JudgeInfo, PublicRound, PublishedRule, ResultInfo } from '../../api/types'
import { apiError, mockApi, renderRoute, type Call } from '../../test/render'

const session = { admin: { id: 'a1', login: 'host.admin' }, expires_at: '2026-10-14T08:00:00Z', csrf_token: 'session-csrf' }

const event: EventInfo = {
  id: 'e1',
  owner_id: 'a1',
  title: '联调项目评审',
  description: '',
  organization: '',
  planned_at: null,
  scoring_rule: null,
  duration_seconds: 180,
  allow_revisions: true,
  screen_title: '',
  screen_theme: 'light',
  show_public_qr: true,
  leaderboard_limit: 10,
  status: 'RUNNING',
  public_code: 'ABCDEFGH2345',
  published_at: '2026-10-14T01:00:00Z',
  version: 5,
  created_at: '2026-10-14T00:00:00Z',
  updated_at: '2026-10-14T00:00:00Z',
}

const judge = (n: number): JudgeInfo => ({
  id: `j${n}`,
  event_id: 'e1',
  number: `00${n}`,
  name: `评委${'甲乙丙丁戊'[n - 1]}`,
  credential_is_set: true,
  credential_source: 'generated',
  credential_version: 1,
  credential_updated_at: '2026-10-14T01:00:00Z',
})

const rule: PublishedRule = {
  mode: 'single',
  criteria: [{ criterion_id: 'total', name: '综合评分', maximum: '100', weight: '1', step: '0.1' }],
  algorithm: 'mean',
  minimum_ballots: 3,
  expected_count: 3,
}

const round = (n: number, patch: Partial<PublicRound> = {}): PublicRound => ({
  id: `r${n}`,
  entry_id: `en${n}`,
  number: `00${n}`,
  name: `项目${'甲乙丙'[n - 1]}`,
  description: '',
  status: 'PENDING',
  version: 1,
  submitted_count: 0,
  expected_count: 3,
  deadline_at: null,
  remaining_seconds: null,
  ...patch,
})

const result = (roundId: string, patch: Partial<ResultInfo['calculation']> = {}, judges = 3): ResultInfo => ({
  id: `res-${roundId}`,
  round_id: roundId,
  round_version: 3,
  rule_id: 's1',
  reason: null,
  source: 'manual',
  closed_at: '2026-10-14T02:00:00Z',
  calculation: {
    rule_version: 1,
    algorithm: 'mean',
    valid_count: judges,
    expected_count: judges,
    minimum_ballots: 3,
    final_score: '90.00',
    missing_judge_ids: [],
    ballots: Array.from({ length: judges }, (_, i) => ({
      judge_id: `j${i + 1}`,
      judge_number: `00${i + 1}`,
      ballot_id: `b${i + 1}`,
      receipt_id: `rc${i + 1}`,
      revision: 1,
      scores: [{ criterion_id: 'total', value: String(85 + i * 5) }],
      total: String(85 + i * 5),
      exclusion: null,
    })),
    ...patch,
  },
})

function snapshot(rounds: PublicRound[], patch: Partial<AdminSnapshot> = {}): AdminSnapshot {
  return {
    role: 'admin',
    version: patch.event?.version ?? event.version,
    server_time: new Date().toISOString(),
    event,
    rule_id: 's1',
    rule_version: 1,
    rule,
    entries: [],
    judges: [judge(1), judge(2), judge(3)],
    rounds,
    results: [],
    ballots: [],
    ranking: [],
    display: { mode: 'waiting', round_id: null, title: event.title, theme: 'light', show_public_qr: true, leaderboard_limit: 10 },
    screen_grants: [],
    ...patch,
  }
}

const writes = (calls: Call[]) => calls.filter(c => c.method !== 'GET' && c.path !== '/realtime/tickets')
const snapshotReads = (calls: Call[]) => calls.filter(c => c.method === 'GET' && c.path === '/events/e1/snapshot').length
const later = (seconds: number) => new Date(Date.now() + seconds * 1000).toISOString()

function openResults() {
  mockApi({ 'GET /auth/me': { body: session }, 'GET /events/e1/snapshot': { body: snapshot([round(1)]) } })
  return renderRoute('/admin/events/e1/results')
}

describe('results export', () => {
  it('defaults to published summary, supports details/audit and warns for unpublished data', async () => {
    const file = { blob: new Blob(['csv']), filename: '中文.csv' }
    const download = vi.spyOn(adminExports, 'download').mockResolvedValue(file)
    const save = vi.spyOn(downloads, 'saveDownload').mockImplementation(() => {})
    const user = userEvent.setup()
    openResults()
    const checkbox = await screen.findByRole('checkbox', { name: '包含未公布' })
    expect(checkbox).not.toBeChecked()
    await user.click(screen.getByRole('button', { name: /下载 CSV/ }))
    await waitFor(() => expect(save).toHaveBeenCalledWith(file))
    expect(download).toHaveBeenLastCalledWith('e1', 'summary', false, expect.any(AbortSignal))
    await user.click(screen.getByRole('combobox', { name: '导出类型' }))
    await user.click(await screen.findByText('评分明细'))
    await user.click(checkbox)
    expect(await screen.findByText(/文件将包含未公布数据/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /下载 CSV/ }))
    await waitFor(() => expect(download).toHaveBeenLastCalledWith('e1', 'details', true, expect.any(AbortSignal)))
    await user.click(screen.getByRole('combobox', { name: '导出类型' }))
    await user.click(await screen.findByText('操作审计', { selector: '.ant-select-item-option-content' }))
    await user.click(screen.getByRole('button', { name: /下载 CSV/ }))
    await waitFor(() => expect(download).toHaveBeenLastCalledWith('e1', 'audit', true, expect.any(AbortSignal)))
  })

  it('prevents overlapping downloads and cancels when leaving the page', async () => {
    let finish!: (value: { blob: Blob; filename: string }) => void
    const download = vi.spyOn(adminExports, 'download').mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const save = vi.spyOn(downloads, 'saveDownload').mockImplementation(() => {})
    const user = userEvent.setup()
    const view = openResults()
    await user.click(await screen.findByRole('button', { name: /下载 CSV/ }))
    const pending = screen.getByRole('button', { name: /正在生成并下载/ })
    expect(screen.getByRole('checkbox', { name: '包含未公布' })).toBeDisabled()
    expect(screen.getByRole('combobox', { name: '导出类型' })).toBeDisabled()
    await user.click(pending)
    expect(download).toHaveBeenCalledTimes(1)
    const signal = download.mock.calls[0][3]!
    view.unmount()
    expect(signal.aborted).toBe(true)
    finish({ blob: new Blob(['csv']), filename: 'late.csv' })
    await Promise.resolve()
    expect(save).not.toHaveBeenCalled()
  })

  it('shows a failed download and allows manual retry without saving an error', async () => {
    const download = vi.spyOn(adminExports, 'download')
      .mockRejectedValueOnce(new ApiError(503, 'SERVICE_UNAVAILABLE', '服务暂时不可用'))
      .mockResolvedValue({ blob: new Blob(['csv']), filename: 'summary.csv' })
    const save = vi.spyOn(downloads, 'saveDownload').mockImplementation(() => {})
    const user = userEvent.setup()
    openResults()
    await user.click(await screen.findByRole('button', { name: /下载 CSV/ }))
    expect(await screen.findByText(/导出失败：服务暂时不可用/)).toBeInTheDocument()
    expect(save).not.toHaveBeenCalled()
    expect(download).toHaveBeenCalledTimes(1)
    await user.click(screen.getByRole('button', { name: /下载 CSV/ }))
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1))
  })

  it('clears the session and returns to login when a download receives 401', async () => {
    vi.spyOn(adminExports, 'download').mockRejectedValue(new ApiError(401, 'SESSION_EXPIRED', '会话失效'))
    const save = vi.spyOn(downloads, 'saveDownload').mockImplementation(() => {})
    const user = userEvent.setup()
    const { router, queryClient } = openResults()
    const button = await screen.findByRole('button', { name: /下载 CSV/ })
    expect(queryClient.getQueryData(queryKeys.adminSnapshot('a1', 'e1'))).toBeDefined()
    await user.click(button)
    expect(await screen.findByText('登录已失效，请重新登录')).toBeInTheDocument()
    await waitFor(() => expect(router.state.location.pathname).toBe('/admin/login'))
    expect(queryClient.getQueryData(queryKeys.adminSnapshot('a1', 'e1'))).toBeUndefined()
    expect(save).not.toHaveBeenCalled()
  })
})

describe('control console', () => {
  it('opens a pending object after confirming N, rule and duration, with no score entry for the host', async () => {
    const calls = mockApi({
      'GET /auth/me': { body: session },
      'GET /events/e1/snapshot': [
        { body: snapshot([round(1), round(2)]) },
        { body: snapshot([round(1, { status: 'OPEN', version: 2, deadline_at: later(180) }), round(2)], { event: { ...event, version: 6 } }) },
      ],
      'POST /rounds/r1/open': { body: {} },
    })
    const user = userEvent.setup()
    renderRoute('/admin/events/e1/control')

    await user.click(await screen.findByRole('button', { name: /开始评分/ }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('开始评分：001 项目甲', { selector: '.ant-modal-confirm-title' })).toBeInTheDocument()
    expect(within(dialog).getByText('3 位评委')).toBeInTheDocument()
    expect(within(dialog).getByText('3 分钟，可暂停')).toBeInTheDocument()
    expect(within(dialog).getByText(/K=3/)).toBeInTheDocument()
    expect(writes(calls)).toHaveLength(0)

    await user.click(within(dialog).getByRole('button', { name: '确认开评' }))
    await waitFor(() => expect(writes(calls)).toHaveLength(1))
    expect(writes(calls)[0]).toMatchObject({ path: '/rounds/r1/open', body: { expected_version: 1 } })
    expect(writes(calls)[0].headers['X-CSRF-Token']).toBe('session-csrf')

    expect(await screen.findByRole('button', { name: /收评/ })).toBeInTheDocument()
    expect(screen.getAllByText('评分中').length).toBeGreaterThan(0)
    expect(screen.getByText(/^0[23]:\d\d$/)).toBeInTheDocument()
    expect(screen.queryAllByRole('spinbutton')).toHaveLength(0)
    expect(screen.queryAllByRole('textbox')).toHaveLength(0)
  })

  it('refreshes instead of resending when the round version is stale', async () => {
    const calls = mockApi({
      'GET /auth/me': { body: session },
      'GET /events/e1/snapshot': [
        { body: snapshot([round(1, { status: 'OPEN', version: 2, deadline_at: later(120), submitted_count: 1 })]) },
        { body: snapshot([round(1, { status: 'PAUSED', version: 3, remaining_seconds: '75.500000', submitted_count: 1 })]) },
      ],
      'POST /rounds/r1/pause': apiError('VERSION_CONFLICT', 409),
    })
    const user = userEvent.setup()
    renderRoute('/admin/events/e1/control')

    await user.click(await screen.findByRole('button', { name: /暂停/ }))
    expect(await screen.findByText(/暂停失败：服务端：VERSION_CONFLICT。已刷新为最新状态/)).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /恢复/ })).toBeInTheDocument()
    expect(screen.getByText('01:16')).toBeInTheDocument()
    expect(writes(calls)).toHaveLength(1)
    expect(writes(calls)[0].body).toEqual({ expected_version: 2 })
  })

  it('requires a reason to close early and sends it with the round version (AT-13)', async () => {
    const calls = mockApi({
      'GET /auth/me': { body: session },
      'GET /events/e1/snapshot': { body: snapshot([round(1, { status: 'OPEN', version: 2, submitted_count: 2 })]) },
      'POST /rounds/r1/close': { body: {} },
    })
    const user = userEvent.setup()
    renderRoute('/admin/events/e1/control')

    await user.click(await screen.findByRole('button', { name: /收评/ }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('未收齐：已交 2 / 应交 3')).toBeInTheDocument()
    expect(within(dialog).getByText(/收评后不能公布/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: '确认收评' }))
    expect(await within(dialog).findByText('请填写收评原因')).toBeInTheDocument()
    expect(writes(calls)).toHaveLength(0)

    await user.type(within(dialog).getByLabelText('收评原因'), ' 评委临时离场 ')
    await user.click(within(dialog).getByRole('button', { name: '确认收评' }))
    await waitFor(() => expect(writes(calls)).toHaveLength(1))
    expect(writes(calls)[0]).toMatchObject({ path: '/rounds/r1/close', body: { expected_version: 2, reason: '评委临时离场' } })
  })

  it('cannot publish below K and marks no result with a reason (AT-12)', async () => {
    const short = result('r1', { algorithm: 'trimmed_mean', valid_count: 4, expected_count: 5, minimum_ballots: 5, final_score: null, missing_judge_ids: ['j3', 'j2'] }, 1)
    const calls = mockApi({
      'GET /auth/me': { body: session },
      'GET /events/e1/snapshot': { body: snapshot([round(1, { status: 'CLOSED', version: 3, submitted_count: 4 })], { results: [short] }) },
      'POST /rounds/r1/no-result': { body: {} },
    })
    const user = userEvent.setup()
    renderRoute('/admin/events/e1/control')

    expect(await screen.findByText('有效 4 份，未达到最低有效份数 K=5，不能公布')).toBeInTheDocument()
    expect(screen.getByText('缺交 2 人（不计零分）：002 评委乙、003 评委丙')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '公布成绩' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重开补评' })).toBeEnabled()

    await user.click(screen.getByRole('button', { name: '标记无结果' }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('无结果原因'), '有效份数不足')
    await user.click(within(dialog).getByRole('button', { name: '确认标记' }))
    await waitFor(() => expect(writes(calls)).toHaveLength(1))
    expect(writes(calls)[0]).toMatchObject({ path: '/rounds/r1/no-result', body: { expected_version: 3, reason: '有效份数不足' } })
  })

  it('publishes after the host reviews exclusions and the final score, then stays on the object', async () => {
    const trimmed = result('r1', { algorithm: 'trimmed_mean' })
    const [low, middle, high] = trimmed.calculation.ballots
    low.exclusion = 'lowest'
    high.exclusion = 'highest'
    middle.total = '90.005'
    trimmed.calculation.ballots = [high, low, middle]
    const calls = mockApi({
      'GET /auth/me': { body: session },
      'GET /events/e1/snapshot': [
        { body: snapshot([round(1, { status: 'CLOSED', version: 3, submitted_count: 3 }), round(2)], { results: [trimmed] }) },
        { body: snapshot([round(1, { status: 'PUBLISHED', version: 4, submitted_count: 3 }), round(2)], { results: [trimmed], event: { ...event, version: 6 } }) },
      ],
      'POST /rounds/r1/publish-result': { body: {} },
    })
    const user = userEvent.setup()
    renderRoute('/admin/events/e1/control')

    expect(await screen.findByText('可以公布：最终成绩 90.00')).toBeInTheDocument()
    expect(screen.getByText('剔除最低')).toBeInTheDocument()
    expect(screen.getByText('剔除最高')).toBeInTheDocument()
    expect(screen.getByText('90.01')).toBeInTheDocument()
    const ballotTable = screen.getByRole('columnheader', { name: '个人总分' }).closest('table')!
    const judgeCells = within(ballotTable).getAllByRole('row').slice(1).map(row => within(row).getAllByRole('cell')[0].textContent)
    expect(judgeCells).toEqual(['001 评委甲', '002 评委乙', '003 评委丙'])

    await user.click(screen.getByRole('button', { name: '公布成绩' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/剔除 2 份/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: '确认公布' }))
    await waitFor(() => expect(writes(calls)).toHaveLength(1))
    expect(writes(calls)[0]).toMatchObject({ path: '/rounds/r1/publish-result', body: { expected_version: 3 } })

    expect(await screen.findByText('下一个待评对象：002 项目乙')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '001 项目甲', level: 4 })).toBeInTheDocument()
  })

  it('locates unfinished objects instead of finishing the event (AT-24)', async () => {
    const calls = mockApi({
      'GET /auth/me': { body: session },
      'GET /events/e1/snapshot': {
        body: snapshot([round(1, { status: 'PUBLISHED', version: 4 }), round(2, { status: 'CLOSED', version: 3 })], {
          results: [result('r1'), result('r2')],
        }),
      },
    })
    const user = userEvent.setup()
    const { router } = renderRoute('/admin/events/e1/control?round=r1')

    await user.click(await screen.findByRole('button', { name: '结束活动' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('还有对象未处理，不能结束活动')).toBeInTheDocument()
    expect(within(dialog).getByText('002 项目乙')).toBeInTheDocument()
    expect(within(dialog).getByText('公布成绩、标记无结果或重开补评')).toBeInTheDocument()
    expect(writes(calls)).toHaveLength(0)

    await user.click(within(dialog).getByRole('button', { name: '定位' }))
    await waitFor(() => expect(router.state.location.search).toBe('?round=r2'))
    expect(await screen.findByText('结果核对')).toBeInTheDocument()
  })

  it('maps task IDs from a rejected finish to object names (G7)', async () => {
    const calls = mockApi({
      'GET /auth/me': { body: session },
      'GET /events/e1/snapshot': [
        { body: snapshot([round(1, { status: 'PUBLISHED' }), round(2, { status: 'SKIPPED' })], { results: [result('r1')] }) },
        { body: snapshot([round(1, { status: 'PUBLISHED' }), round(2, { status: 'CLOSED' })], { results: [result('r1'), result('r2')] }) },
      ],
      'POST /events/e1/finish': apiError('UNFINISHED_ROUNDS', 409, { message: '待处理任务：r2' }),
    })
    const user = userEvent.setup()
    renderRoute('/admin/events/e1/control')

    await user.click(await screen.findByRole('button', { name: '结束活动' }))
    await user.click(await screen.findByRole('button', { name: '确认结束' }))
    expect(await screen.findByText('还有对象未处理，不能结束活动')).toBeInTheDocument()
    expect(writes(calls)[0]).toMatchObject({ path: '/events/e1/finish', body: { expected_version: 5 } })
    const dialog = screen.getByText('还有对象未处理，不能结束活动').closest<HTMLElement>('[role="dialog"]')!
    expect(await within(dialog).findByText('002 项目乙')).toBeInTheDocument()
  })

  it('verifies by re-reading the snapshot when the outcome is unknown', async () => {
    const calls = mockApi({
      'GET /auth/me': { body: session },
      'GET /events/e1/snapshot': { body: snapshot([round(1)]) },
      'POST /rounds/r1/open': () => {
        throw new TypeError('Failed to fetch')
      },
    })
    const user = userEvent.setup()
    renderRoute('/admin/events/e1/control')

    await user.click(await screen.findByRole('button', { name: /开始评分/ }))
    await user.click(await screen.findByRole('button', { name: '确认开评' }))
    expect(await screen.findByText('开始评分：结果未知', { selector: '.ant-modal-confirm-title' })).toBeInTheDocument()
    expect(screen.getByText(/不要连续重复点击/)).toBeInTheDocument()
    await waitFor(() => expect(snapshotReads(calls)).toBeGreaterThanOrEqual(2))
    expect(writes(calls)).toHaveLength(1)
  })

  it('shows submitted status per judge without scores', async () => {
    mockApi({
      'GET /auth/me': { body: session },
      'GET /events/e1/snapshot': {
        body: snapshot([round(1, { status: 'OPEN', version: 2, submitted_count: 1 })], {
          ballots: [
            {
              judge_id: 'j2',
              receipts: [1, 2].map(revision => ({
                ballot_id: 'b2',
                receipt_id: `rc${revision}`,
                round_id: 'r1',
                revision,
                rule_version: 1,
                scores: [{ criterion_id: 'total', value: '77.7' }],
                total_score: '77.70',
                accepted_at: '2026-10-14T02:00:00Z',
              })),
            },
          ],
        }),
      },
    })
    renderRoute('/admin/events/e1/control')
    const panel = (await screen.findByText('评委状态')).closest<HTMLElement>('.ant-card')!
    const rows = within(panel).getAllByRole('listitem')
    expect(within(rows[0]).getByText('未交')).toBeInTheDocument()
    expect(within(rows[1]).getByText('已交')).toBeInTheDocument()
    expect(within(rows[1]).getByText(/第 2 版/)).toBeInTheDocument()
    expect(within(panel).getByText('已交 1 / 3')).toBeInTheDocument()
    expect(screen.queryByText('77.70')).not.toBeInTheDocument()
  })

  it('explains that drafts have no console', async () => {
    mockApi({
      'GET /auth/me': { body: session },
      'GET /events/e1/snapshot': apiError('EVENT_NOT_PUBLISHED', 409),
    })
    renderRoute('/admin/events/e1/control')
    expect(await screen.findByText('活动尚未发布')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '去发布检查' })).toHaveAttribute('href', '/admin/events/e1/settings?tab=publish')
  })
})

describe('results page', () => {
  it('shows the ranking, close history and ballot versions', async () => {
    const first = { ...result('r1', { final_score: null, valid_count: 2, missing_judge_ids: ['j3'] }, 2), id: 'res-a', round_version: 3, reason: '评委离场' }
    const second = { ...result('r1'), id: 'res-b', round_version: 5, source: 'deadline' as const }
    mockApi({
      'GET /auth/me': { body: session },
      'GET /events/e1/snapshot': {
        body: snapshot([round(1, { status: 'PUBLISHED', version: 6, submitted_count: 3 })], {
          event: { ...event, status: 'FINISHED' },
          results: [first, second],
          ranking: [{ entry_id: 'en1', number: '001', name: '项目甲', final_score: '90.00', rank: 1 }],
          ballots: [
            {
              judge_id: 'j1',
              receipts: [
                {
                  ballot_id: 'b1',
                  receipt_id: 'receipt-0001',
                  round_id: 'r1',
                  revision: 1,
                  rule_version: 1,
                  scores: [{ criterion_id: 'total', value: '85' }],
                  total_score: '85.00',
                  accepted_at: '2026-10-14T02:00:00Z',
                },
              ],
            },
          ],
        }),
      },
    })
    const user = userEvent.setup()
    renderRoute('/admin/events/e1/results')

    const ranking = (await screen.findByText('最终排名')).closest<HTMLElement>('.ant-card')!
    expect(within(ranking).getByText('项目甲')).toBeInTheDocument()
    expect(within(ranking).getByText('90.00')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /展开行|Expand row/ }))
    expect(await screen.findByText('第 2 次收评（当前结果）')).toBeInTheDocument()
    expect(screen.getByText('第 1 次收评')).toBeInTheDocument()
    expect(screen.getByText(/到时自动收评/)).toBeInTheDocument()
    expect(screen.getByText('评委离场')).toBeInTheDocument()
    expect(screen.getByText('receipt-0001')).toBeInTheDocument()
  })
})
