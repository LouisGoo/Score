import { createClient, memoryToken, request } from './client'
import type { CSRFInfo, SessionInfo } from './types'

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
