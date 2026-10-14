import type { BallotReceipt, JudgeSessionInfo, JudgeSnapshot, PreviewInfo } from '../api/types'

export const judgeSession: JudgeSessionInfo = {
  judge: { id: 'j1', event_id: 'e1', number: '01', name: '陈评委' },
  csrf_token: 'judge-csrf', expires_at: '2099-01-01T00:00:00Z', read_only: false,
}
export const previewInfo: PreviewInfo = {
  public_code: 'ABCDEFGH2345', title: '创新项目评审', description: '请独立评分', organization: '评审委员会',
  planned_at: null, status: 'RUNNING', exchange_open: true,
}
export function judgeSnapshot(): JudgeSnapshot {
  return {
    role: 'judge', version: 1, server_time: new Date().toISOString(),
    event: { id: 'e1', title: previewInfo.title, description: previewInfo.description, organization: previewInfo.organization, status: 'RUNNING', public_code: previewInfo.public_code },
    identity: { id: 'j1', number: '01', name: '陈评委' }, rule_id: 'rule1', rule_version: 1, allow_revisions: true,
    rule: { mode: 'multi', algorithm: 'mean', expected_count: 5, minimum_ballots: 3, criteria: [
      { criterion_id: 'a', name: '内容质量', maximum: '100', weight: '0.5', step: '1' },
      { criterion_id: 'b', name: '表达能力', maximum: '10', weight: '0.3', step: '0.1' },
      { criterion_id: 'c', name: '创新价值', maximum: '20', weight: '0.2', step: '1' },
    ] },
    rounds: [
      { id: 'r1', entry_id: 'entry1', number: '001', name: '智慧校园', description: '第一组项目介绍', status: 'OPEN', version: 1, submitted_count: 0, expected_count: 5, deadline_at: null, remaining_seconds: null },
      { id: 'r2', entry_id: 'entry2', number: '002', name: '绿色出行', description: '', status: 'PENDING', version: 1, submitted_count: 0, expected_count: 5, deadline_at: null, remaining_seconds: null },
    ], my_ballots: [], published_results: [], ranking: [],
  }
}
export function ballotReceipt(overrides: Partial<BallotReceipt> = {}): BallotReceipt {
  return { ballot_id: 'ballot1', receipt_id: 'receipt-1', round_id: 'r1', revision: 1, rule_version: 1,
    scores: [{ criterion_id: 'a', value: '90' }, { criterion_id: 'b', value: '8' }, { criterion_id: 'c', value: '18' }],
    total_score: '87.00', accepted_at: '2026-10-14T10:00:00Z', ...overrides }
}
