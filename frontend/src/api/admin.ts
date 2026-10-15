import { createClient, memoryToken, request } from './client'
import type { paths } from './schema'
import type {
  AdminSnapshot,
  CloseInput,
  ControlInput,
  CredentialResult,
  CSRFInfo,
  EntryCreate,
  EntryInfo,
  EntryPatch,
  EventCreate,
  EventInfo,
  EventListItem,
  EventPatch,
  JudgeCreate,
  JudgeInfo,
  JudgePatch,
  PublicationInfo,
  PublishCheck,
  PublishResult,
  ReopenInput,
  RoundState,
  SessionInfo,
  SkipInput,
  CreatedGrant,
  GrantInfo,
  ScreenDisplay,
  ScreenSettings,
} from './types'

const sessionCsrf = memoryToken()

function remember(info: SessionInfo): SessionInfo {
  sessionCsrf.set(info.csrf_token)
  return info
}

/** 主办方会话：登录前使用双提交 CSRF，登录后使用会话 CSRF；两者都只存内存。 */
export const adminAuth = {
  async login(login: string, password: string): Promise<SessionInfo> {
    const prelogin = await request<CSRFInfo>('/auth/csrf')
    return remember(
      await request<SessionInfo>('/auth/login', {
        method: 'POST',
        body: { login, password },
        headers: { 'X-CSRF-Token': prelogin.csrf_token },
      }),
    )
  },
  async me(): Promise<SessionInfo> {
    return remember(await request<SessionInfo>('/auth/me'))
  },
  async logout(): Promise<void> {
    try {
      await adminApi.send('POST', '/auth/logout')
    } finally {
      sessionCsrf.set(null)
    }
  },
  forget() {
    sessionCsrf.set(null)
  },
}

export const adminApi = createClient({
  csrf: {
    get: sessionCsrf.get,
    refresh: async () => {
      await adminAuth.me()
    },
  },
})

const PAGE_SIZE = 100
/** 列表接口 offset 上限为 1000000；按 P0 规模（≤100 对象、≤50 评委）逐页读完。 */
const MAX_PAGES = 50

async function listAll<T>(path: string, signal?: AbortSignal): Promise<T[]> {
  const items: T[] = []
  for (let page = 0; page < MAX_PAGES; page++) {
    const batch = await adminApi.get<T[]>(`${path}?offset=${page * PAGE_SIZE}&limit=${PAGE_SIZE}`, { signal })
    items.push(...batch)
    if (batch.length < PAGE_SIZE) break
  }
  return items
}

const id = encodeURIComponent
const eventPath = (eventId: string) => `/events/${id(eventId)}`

export type ExportKind = paths['/api/v1/events/{event_id}/exports/{kind}']['get']['parameters']['path']['kind']

export const adminExports = {
  download: (eventId: string, kind: ExportKind, includeUnpublished = false, signal?: AbortSignal) =>
    adminApi.download(`${eventPath(eventId)}/exports/${kind}?include_unpublished=${includeUnpublished}`, { signal }),
}

/** 主办方活动管理。写操作均无幂等键：超时后由调用方先查询核验，不自动重发。 */
export const adminEvents = {
  list: (signal?: AbortSignal) => listAll<EventListItem>('/events', signal),
  get: (eventId: string, signal?: AbortSignal) => adminApi.get<EventInfo>(eventPath(eventId), { signal }),
  create: (body: EventCreate) => adminApi.send<EventInfo>('POST', '/events', body),
  patch: (eventId: string, body: EventPatch) => adminApi.send<EventInfo>('PATCH', eventPath(eventId), body),
  remove: (eventId: string) => adminApi.send<void>('DELETE', eventPath(eventId)),
  copy: (eventId: string) => adminApi.send<EventInfo>('POST', `${eventPath(eventId)}/copy`),

  entries: (eventId: string, signal?: AbortSignal) => listAll<EntryInfo>(`${eventPath(eventId)}/entries`, signal),
  createEntry: (eventId: string, body: EntryCreate) =>
    adminApi.send<EntryInfo>('POST', `${eventPath(eventId)}/entries`, body),
  patchEntry: (eventId: string, entryId: string, body: EntryPatch) =>
    adminApi.send<EntryInfo>('PATCH', `${eventPath(eventId)}/entries/${id(entryId)}`, body),
  removeEntry: (eventId: string, entryId: string) =>
    adminApi.send<void>('DELETE', `${eventPath(eventId)}/entries/${id(entryId)}`),

  judges: (eventId: string, signal?: AbortSignal) => listAll<JudgeInfo>(`${eventPath(eventId)}/judges`, signal),
  createJudge: (eventId: string, body: JudgeCreate) =>
    adminApi.send<JudgeInfo>('POST', `${eventPath(eventId)}/judges`, body),
  patchJudge: (eventId: string, judgeId: string, body: JudgePatch) =>
    adminApi.send<JudgeInfo>('PATCH', `${eventPath(eventId)}/judges/${id(judgeId)}`, body),
  removeJudge: (eventId: string, judgeId: string) =>
    adminApi.send<void>('DELETE', `${eventPath(eventId)}/judges/${id(judgeId)}`),

  /** 草稿设置身份码；code 为 null 时自动生成。明文仅在本次响应中返回，调用方不得缓存。 */
  setCredential: (eventId: string, judgeId: string, code: string | null) =>
    adminApi.send<CredentialResult>('PUT', `${eventPath(eventId)}/judges/${id(judgeId)}/credential`, { code }),
  /** 发布后至结束前重置身份码，撤销旧会话；明文同样仅返回一次。 */
  resetCredential: (eventId: string, judgeId: string, reason: string, code: string | null) =>
    adminApi.send<CredentialResult>('POST', `${eventPath(eventId)}/judges/${id(judgeId)}/reset-credential`, {
      reason,
      code,
    }),

  publishCheck: (eventId: string, signal?: AbortSignal) =>
    adminApi.get<PublishCheck>(`${eventPath(eventId)}/publish-check`, { signal }),
  publish: (eventId: string) => adminApi.send<PublishResult>('POST', `${eventPath(eventId)}/publish`),
  publication: (eventId: string, signal?: AbortSignal) =>
    adminApi.get<PublicationInfo>(`${eventPath(eventId)}/publication`, { signal }),
}

const roundPath = (roundId: string) => `/rounds/${id(roundId)}`
const control = (roundId: string, action: string, body: ControlInput | CloseInput | ReopenInput | SkipInput) =>
  adminApi.send<RoundState>('POST', `${roundPath(roundId)}/${action}`, body)

/**
 * 主持人控制台。expected_version 对任务操作为任务版本，对结束/归档为活动版本；
 * 均无幂等键：超时或断网后先重新读取快照核验，不自动重发。
 */
export const adminConsole = {
  snapshot: (eventId: string, signal?: AbortSignal) =>
    adminApi.get<AdminSnapshot>(`${eventPath(eventId)}/snapshot`, { signal }),

  open: (roundId: string, version: number) => control(roundId, 'open', { expected_version: version }),
  pause: (roundId: string, version: number) => control(roundId, 'pause', { expected_version: version }),
  resume: (roundId: string, version: number) => control(roundId, 'resume', { expected_version: version }),
  skip: (roundId: string, version: number, reason: string) => control(roundId, 'skip', { expected_version: version, reason }),
  /** 未收齐时原因必填；已收齐可省略（null）。 */
  close: (roundId: string, version: number, reason: string | null) =>
    control(roundId, 'close', { expected_version: version, reason }),
  /** duration_seconds 为 null 表示不限时；新截止时间按服务端锁内时间计算。 */
  reopen: (roundId: string, version: number, reason: string, durationSeconds: number | null) =>
    control(roundId, 'reopen', { expected_version: version, reason, duration_seconds: durationSeconds }),
  publishResult: (roundId: string, version: number) => control(roundId, 'publish-result', { expected_version: version }),
  noResult: (roundId: string, version: number, reason: string) =>
    control(roundId, 'no-result', { expected_version: version, reason }),

  finish: (eventId: string, version: number) =>
    adminApi.send<EventInfo>('POST', `${eventPath(eventId)}/finish`, { expected_version: version }),
  archive: (eventId: string, version: number) =>
    adminApi.send<EventInfo>('POST', `${eventPath(eventId)}/archive`, { expected_version: version }),
}

/** Grant tokens are returned only once: keep create results in component state, never query/mutation data. */
export const adminScreens = {
  create: (eventId: string, ttlSeconds: number) =>
    adminApi.send<CreatedGrant>('POST', `${eventPath(eventId)}/screen-grants`, { ttl_seconds: ttlSeconds }),
  list: (eventId: string, signal?: AbortSignal) =>
    adminApi.get<GrantInfo[]>(`${eventPath(eventId)}/screen-grants`, { signal }),
  revoke: (eventId: string, grantId: string) =>
    adminApi.send<void>('DELETE', `${eventPath(eventId)}/screen-grants/${id(grantId)}`),
  display: (eventId: string, body: ScreenSettings) =>
    adminApi.send<ScreenDisplay>('PUT', `${eventPath(eventId)}/screen`, body),
}
