import { createClient, memoryToken, request } from './client'
import type {
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
  SessionInfo,
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
