import { createClient, memoryToken, request } from './client'
import type { CSRFInfo, ConfirmationInfo, JudgeSessionInfo, PreviewInfo } from './types'

const bootstrapCsrf = memoryToken()
const sessionCsrf = memoryToken()

function remember(info: JudgeSessionInfo): JudgeSessionInfo {
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
    sessionCsrf.set(null)
    bootstrapCsrf.set(null)
  },
}

export const judgeApi = createClient({
  csrf: {
    get: sessionCsrf.get,
    refresh: async () => {
      await judgeAuth.me()
    },
  },
})
