/**
 * 评委手机草稿：按活动、评委、任务、规则版本分键保存在本机，
 * 切换任务不会把旧对象的分数带入新对象；退出身份时清理该评委的全部草稿。
 */
const PREFIX = 'score:draft:'

export interface DraftScope {
  eventId: string
  judgeId: string
  roundId: string
  ruleVersion: number
}

export type DraftScores = Record<string, string>

function judgePrefix(eventId: string, judgeId: string) {
  return `${PREFIX}${eventId}:${judgeId}:`
}

export function draftKey(scope: DraftScope): string {
  return `${judgePrefix(scope.eventId, scope.judgeId)}${scope.roundId}:${scope.ruleVersion}`
}

export function loadDraft(scope: DraftScope, storage: Storage = localStorage): DraftScores | null {
  try {
    const raw = storage.getItem(draftKey(scope))
    if (raw === null) return null
    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null
    const entries = Object.entries(parsed).filter((e): e is [string, string] => typeof e[1] === 'string')
    return Object.fromEntries(entries)
  } catch {
    return null
  }
}

export function saveDraft(scope: DraftScope, scores: DraftScores, storage: Storage = localStorage): void {
  try {
    storage.setItem(draftKey(scope), JSON.stringify(scores))
  } catch {
    // 存储已满或被禁用（如部分隐私模式）时仅失去草稿，不影响提交。
  }
}

export function clearDraft(scope: DraftScope, storage: Storage = localStorage): void {
  storage.removeItem(draftKey(scope))
}

export function clearJudgeDrafts(eventId: string, judgeId: string, storage: Storage = localStorage): void {
  const prefix = judgePrefix(eventId, judgeId)
  const keys: string[] = []
  for (let i = 0; i < storage.length; i += 1) {
    const key = storage.key(i)
    if (key?.startsWith(prefix)) keys.push(key)
  }
  keys.forEach(key => storage.removeItem(key))
}
