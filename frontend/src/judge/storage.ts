import type { BallotInput } from '../api/types'
import { draftKey, type DraftScope } from '../lib/drafts'

const PREFIX = 'score:submission:'
export interface PendingSubmission {
  scope: DraftScope
  key: string
  body: BallotInput
}
const keyFor = (scope: DraftScope) => PREFIX + draftKey(scope)

/** Store the immutable request BEFORE sending; no new key until this attempt is resolved. */
export function saveSubmission(value: PendingSubmission): boolean {
  try {
    const existing = localStorage.getItem(keyFor(value.scope))
    if (existing && JSON.parse(existing).key !== value.key) return false
    localStorage.setItem(keyFor(value.scope), JSON.stringify(value))
    return true
  } catch {
    return false
  }
}

export function pendingSubmissions(eventId: string, judgeId: string): PendingSubmission[] {
  try {
    const found: PendingSubmission[] = []
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (!key?.startsWith(PREFIX)) continue
      try {
        const item = JSON.parse(localStorage.getItem(key)!) as PendingSubmission
        if (item.scope?.eventId !== eventId || item.scope?.judgeId !== judgeId) continue
        if (typeof item.scope.roundId !== 'string' || !Number.isInteger(item.scope.ruleVersion)
          || typeof item.key !== 'string' || !/^[0-9a-f-]{36}$/i.test(item.key)
          || !Array.isArray(item.body?.scores) || item.body.rule_version !== item.scope.ruleVersion
          || !Number.isInteger(item.body.expected_ballot_revision)
          || !item.body.scores.every(s => typeof s.criterion_id === 'string' && typeof s.value === 'string')
          || key !== keyFor(item.scope)) continue
        found.push(item)
      } catch { /* Ignore a damaged entry without affecting other rounds. */ }
    }
    return found
  } catch {
    return []
  }
}

export function clearSubmission(scope: DraftScope, expectedKey: string) {
  try {
    const raw = localStorage.getItem(keyFor(scope))
    if (raw && JSON.parse(raw).key === expectedKey) localStorage.removeItem(keyFor(scope))
  } catch { /* Receipt remains authoritative. */ }
}

export function clearJudgeSubmissions(eventId: string, judgeId: string) {
  pendingSubmissions(eventId, judgeId).forEach(item => clearSubmission(item.scope, item.key))
}
