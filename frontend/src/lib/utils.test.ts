import { describe, expect, it } from 'vitest'
import { clockOffset, formatCountdown, pausedRemainingMs, remainingMs } from './clock'
import { clearDraft, clearJudgeDrafts, loadDraft, saveDraft } from './drafts'
import { fragmentUrl, takeFragmentParams } from './fragment'
import { newIdempotencyKey } from './ids'
import { jittered, preferNewer } from './polling'

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

describe('clock', () => {
  it('derives countdown from server offset rather than local clock', () => {
    const offset = clockOffset('2026-10-14T00:00:10.000Z', Date.parse('2026-10-14T00:00:00.000Z'))
    expect(offset).toBe(10_000)
    const now = Date.parse('2026-10-14T00:00:00.000Z')
    expect(remainingMs('2026-10-14T00:01:00.000Z', offset, now)).toBe(50_000)
    expect(remainingMs('2026-10-14T00:00:05.000Z', offset, now)).toBe(0)
    expect(remainingMs(null, offset, now)).toBeNull()
  })

  it('formats paused remaining seconds and rounds countdown up', () => {
    expect(pausedRemainingMs('12.345678')).toBe(12_346)
    expect(pausedRemainingMs(null)).toBeNull()
    expect(formatCountdown(61_001)).toBe('01:02')
    expect(formatCountdown(0)).toBe('00:00')
    expect(formatCountdown(null)).toBe('不限时')
  })
})

describe('polling', () => {
  it('keeps jitter within ±20%', () => {
    expect(jittered(5000, 0.2, () => 0)).toBe(4000)
    expect(jittered(5000, 0.2, () => 1)).toBe(6000)
    expect(jittered(5000, 0.2, () => 0.5)).toBe(5000)
  })

  it('ignores out-of-order older snapshots but accepts the same version', () => {
    const current = { version: 5, server_time: 'a' }
    expect(preferNewer(current, { version: 4, server_time: 'b' })).toBe(current)
    expect(preferNewer(current, { version: 5, server_time: 'c' }).server_time).toBe('c')
    expect(preferNewer(undefined, current)).toBe(current)
  })
})

describe('fragment', () => {
  it('reads credentials from the fragment and removes them from the address bar', () => {
    window.history.replaceState(null, '', '/join/ABCDEFGH2345?from=qr#code=FIRST123&other=x')
    expect(takeFragmentParams(['code'])).toEqual({ code: 'FIRST123' })
    expect(window.location.hash).toBe('')
    expect(window.location.pathname + window.location.search).toBe('/join/ABCDEFGH2345?from=qr')
  })

  it('leaves the URL untouched when there is no fragment', () => {
    window.history.replaceState(null, '', '/screen/g1')
    expect(takeFragmentParams(['token'])).toEqual({})
    expect(window.location.pathname).toBe('/screen/g1')
  })

  it('builds fragment links without putting secrets in the query string', () => {
    const url = fragmentUrl('https://score.test/', '/screen/g1', { token: 'a+b/c' })
    expect(url).toBe('https://score.test/screen/g1#token=a%2Bb%2Fc')
    expect(new URL(url).search).toBe('')
  })
})

describe('idempotency key', () => {
  it('uses randomUUID when available', () => {
    expect(newIdempotencyKey()).toMatch(UUID_V4)
  })

  it('falls back to getRandomValues outside secure contexts', () => {
    const insecure = {
      getRandomValues: <T extends ArrayBufferView>(array: T) => crypto.getRandomValues(array as never) as T,
    } as Crypto
    const keys = new Set(Array.from({ length: 50 }, () => newIdempotencyKey(insecure)))
    expect(keys.size).toBe(50)
    keys.forEach(key => expect(key).toMatch(UUID_V4))
  })
})

describe('drafts', () => {
  const scope = { eventId: 'e1', judgeId: 'j1', roundId: 'r1', ruleVersion: 1 }

  it('isolates drafts by round and rule version', () => {
    saveDraft(scope, { total: '90.0' })
    expect(loadDraft(scope)).toEqual({ total: '90.0' })
    expect(loadDraft({ ...scope, roundId: 'r2' })).toBeNull()
    expect(loadDraft({ ...scope, ruleVersion: 2 })).toBeNull()
    expect(loadDraft({ ...scope, judgeId: 'j2' })).toBeNull()
    clearDraft(scope)
    expect(loadDraft(scope)).toBeNull()
  })

  it('clears only the signed-out judge and ignores corrupt entries', () => {
    saveDraft(scope, { total: '1' })
    saveDraft({ ...scope, roundId: 'r2' }, { total: '2' })
    saveDraft({ ...scope, judgeId: 'j2' }, { total: '3' })
    clearJudgeDrafts('e1', 'j1')
    expect(loadDraft(scope)).toBeNull()
    expect(loadDraft({ ...scope, roundId: 'r2' })).toBeNull()
    expect(loadDraft({ ...scope, judgeId: 'j2' })).toEqual({ total: '3' })
    localStorage.setItem('score:draft:e1:j1:r9:1', '{bad json')
    expect(loadDraft({ ...scope, roundId: 'r9' })).toBeNull()
  })
})
