import { ApiError, createClient, memoryToken, request } from './client'
import type { BallotInput, BallotReceipt, CSRFInfo, ConfirmationInfo, JudgeSessionInfo, JudgeSnapshot, PreviewInfo } from './types'

const bootstrapCsrf = memoryToken()
const sessionCsrf = memoryToken()
let sessionIdentity: string | null = null
const identityOf = (info: JudgeSessionInfo) => `${info.judge.event_id}:${info.judge.id}`

function remember(info: JudgeSessionInfo): JudgeSessionInfo {
  sessionIdentity = identityOf(info)
  sessionCsrf.set(info.csrf_token)
  return info
}

async function bootstrap(): Promise<string> {
  const info = await request<CSRFInfo>('/judge-sessions/csrf')
  bootstrapCsrf.set(info.csrf_token)
  return info.csrf_token
}

/** 兑换前专用：bootstrap CSRF 与浏览器 Cookie 绑定，不能替代会话 CSRF。 */
const exchangeApi = createClient({ csrf: { get: bootstrapCsrf.get, refresh: async () => void (await bootstrap()) } })

/** 评委会话：预览 → bootstrap → verify → 用户确认姓名编号 → exchange；之后 me 恢复。 */
export const judgeAuth = {
  preview(publicCode: string): Promise<PreviewInfo> {
    return request<PreviewInfo>(`/join/${encodeURIComponent(publicCode.trim().toUpperCase())}`)
  },
  async verify(publicCode: string, code: string): Promise<ConfirmationInfo> {
    if (!bootstrapCsrf.get()) await bootstrap()
    return exchangeApi.send<ConfirmationInfo>('POST', '/judge-sessions/verify', {
      public_code: publicCode,
      code,
    })
  },
  async exchange(confirmationToken: string): Promise<JudgeSessionInfo> {
    const info = await exchangeApi.send<JudgeSessionInfo>('POST', '/judge-sessions/exchange', {
      confirmation_token: confirmationToken,
    })
    bootstrapCsrf.set(null)
    return remember(info)
  },
  async me(): Promise<JudgeSessionInfo> {
    return remember(await request<JudgeSessionInfo>('/judge-sessions/me'))
  },
  async logout(): Promise<void> {
    try {
      await judgeApi.send('POST', '/judge-sessions/logout')
    } finally {
      sessionCsrf.set(null)
    }
  },
  forget() {
    sessionIdentity = null
    sessionCsrf.set(null)
    bootstrapCsrf.set(null)
  },
}

export const judgeApi = createClient({
  csrf: {
    get: sessionCsrf.get,
    refresh: async () => {
      const expectedIdentity = sessionIdentity
      const info = await request<JudgeSessionInfo>('/judge-sessions/me')
      if (expectedIdentity && identityOf(info) !== expectedIdentity) {
        sessionCsrf.set(null)
        throw new ApiError(401, 'SESSION_EXPIRED', '评委身份已在其他页面切换，请重新确认身份')
      }
      remember(info)
    },
  },
})

export const judgeScoring = {
  snapshot(eventId: string, signal?: AbortSignal) {
    return judgeApi.get<JudgeSnapshot>(`/judge/events/${encodeURIComponent(eventId)}/snapshot`, { signal })
  },
  submit(roundId: string, body: BallotInput, key: string) {
    return judgeApi.send<BallotReceipt>('PUT', `/rounds/${encodeURIComponent(roundId)}/my-ballot`, body, {
      headers: { 'Idempotency-Key': key },
    })
  },
  receipt(roundId: string, key: string) {
    return judgeApi.get<BallotReceipt>(`/rounds/${encodeURIComponent(roundId)}/my-ballot`, {
      headers: { 'Idempotency-Key': key },
    })
  },
}
