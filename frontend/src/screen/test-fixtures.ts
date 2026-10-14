import type { AdminSnapshot, ScreenSnapshot } from '../api/types'

export const screenToken = 'A'.repeat(43)
export const adminSession = { admin: { id: 'a1', login: 'host' }, expires_at: '2099-01-01T00:00:00Z', csrf_token: 'admin-csrf' }
export function screenSnapshot(mode: ScreenSnapshot['display']['mode'] = 'waiting'): ScreenSnapshot {
  const target = ['progress', 'paused', 'result'].includes(mode)
  return {
    role: 'screen', version: 5, server_time: new Date().toISOString(),
    event: { id: 'e1', title: '创新项目评审', description: '欢迎各位评委与嘉宾', organization: '评审委员会', status: mode === 'ended' ? 'FINISHED' : 'RUNNING', public_code: 'ABCDEFGH2345' },
    display: { mode, round_id: target ? 'r1' : null, title: '年度创新评审', theme: 'dark', show_public_qr: true, leaderboard_limit: 10 },
    current_round: target ? { id: 'r1', entry_id: 'en1', number: '001', name: '智慧校园', description: '以创新改善校园生活', status: mode === 'result' ? 'PUBLISHED' : mode === 'paused' ? 'PAUSED' : 'OPEN', version: 2, submitted_count: 3, expected_count: 5, deadline_at: new Date(Date.now() + 90000).toISOString(), remaining_seconds: '75' } : null,
    published_results: [{ round_id: 'r1', entry_id: 'en1', number: '001', name: '智慧校园', final_score: '90.50', valid_count: 5, expected_count: 5, minimum_ballots: 3, algorithm: 'trimmed_mean', rule_version: 1, published_at: '2026-10-14T11:00:00Z' }],
    ranking: [{ entry_id: 'en1', number: '001', name: '智慧校园', final_score: '90.50', rank: 1 }],
  }
}

export function adminScreenSnapshot(): AdminSnapshot {
  const publicData = screenSnapshot('progress')
  const rule = { mode: 'single' as const, criteria: [{ criterion_id: 'a', name: '综合评分', maximum: '100', step: '0.1', weight: '1' }], algorithm: 'mean' as const, expected_count: 5, minimum_ballots: 3 }
  return {
    role: 'admin', version: 5, server_time: publicData.server_time,
    event: { ...publicData.event, version: 5, owner_id: 'a1', planned_at: null, scoring_rule: rule, duration_seconds: 180,
      allow_revisions: true, screen_title: '', screen_theme: 'dark', show_public_qr: true, leaderboard_limit: 10,
      published_at: publicData.server_time, created_at: publicData.server_time, updated_at: publicData.server_time },
    rule_id: 'rule1', rule_version: 1, rule, entries: [], judges: [], results: [], ballots: [], ranking: [],
    rounds: [publicData.current_round!], display: publicData.display, screen_grants: [],
  }
}
