import { describe, expect, it } from 'vitest'
import type { PublicRound } from '../../api/types'
import { formatScore } from '../../lib/decimal'
import { defaultRoundId, judgeStatuses, nextPendingRound, parseUnfinishedIds, unfinishedRounds } from './model'

const round = (id: string, status: PublicRound['status']): PublicRound => ({
  id,
  entry_id: id,
  number: id,
  name: id,
  description: '',
  status,
  version: 1,
  submitted_count: 0,
  expected_count: 3,
  deadline_at: null,
  remaining_seconds: null,
})

const receipt = (roundId: string, revision: number) => ({
  ballot_id: 'b',
  receipt_id: `${roundId}-${revision}`,
  round_id: roundId,
  revision,
  rule_version: 1,
  scores: [],
  total_score: '0.00',
  accepted_at: `2026-10-14T02:0${revision}:00Z`,
})

describe('console model', () => {
  it('selects the active round, then one waiting to publish, then the next pending', () => {
    expect(defaultRoundId([round('a', 'PUBLISHED'), round('b', 'PENDING'), round('c', 'PAUSED')])).toBe('c')
    expect(defaultRoundId([round('a', 'PUBLISHED'), round('b', 'PENDING'), round('c', 'CLOSED')])).toBe('c')
    expect(defaultRoundId([round('a', 'PUBLISHED'), round('b', 'PENDING')])).toBe('b')
    expect(defaultRoundId([round('a', 'SKIPPED')])).toBe('a')
    expect(defaultRoundId([])).toBeNull()
  })

  it('finds the next pending round after the current one, wrapping around', () => {
    const rounds = [round('a', 'PENDING'), round('b', 'PUBLISHED'), round('c', 'PENDING'), round('d', 'CLOSED')]
    expect(nextPendingRound(rounds, 'b')?.id).toBe('c')
    expect(nextPendingRound(rounds, 'd')?.id).toBe('a')
    expect(nextPendingRound([round('a', 'PUBLISHED')], 'a')).toBeUndefined()
  })

  it('treats published, skipped and no-result as finished', () => {
    const rounds = (['PENDING', 'OPEN', 'PAUSED', 'CLOSED', 'PUBLISHED', 'SKIPPED', 'NO_RESULT'] as const).map(s => round(s, s))
    expect(unfinishedRounds(rounds).map(r => r.id)).toEqual(['PENDING', 'OPEN', 'PAUSED', 'CLOSED'])
  })

  it('extracts task IDs from the UNFINISHED_ROUNDS message', () => {
    expect(parseUnfinishedIds('待处理任务：a1,b2')).toEqual(['a1', 'b2'])
    expect(parseUnfinishedIds('待处理任务: a1， b2 ')).toEqual(['a1', 'b2'])
    expect(parseUnfinishedIds('仍有未处理的任务')).toEqual([])
  })

  it('derives each judge’s current revision for the round only', () => {
    const judges = ['j1', 'j2'].map(id => ({
      id,
      event_id: 'e',
      number: id,
      name: id,
      credential_is_set: true,
      credential_source: null,
      credential_version: 1,
      credential_updated_at: null,
    }))
    const statuses = judgeStatuses({ judges, ballots: [{ judge_id: 'j1', receipts: [receipt('r1', 1), receipt('r1', 2), receipt('r2', 1)] }] }, 'r1')
    expect(statuses.map(s => [s.judge.id, s.revision, s.acceptedAt])).toEqual([
      ['j1', 2, '2026-10-14T02:02:00Z'],
      ['j2', 0, null],
    ])
  })

  it('rounds high-precision totals half up to two places', () => {
    expect(formatScore('86.666666666666666666666666667')).toBe('86.67')
    expect(formatScore('90.005')).toBe('90.01')
    expect(formatScore('90.004999')).toBe('90.00')
    expect(formatScore('100')).toBe('100.00')
  })
})
