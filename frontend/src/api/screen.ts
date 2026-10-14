import { createClient } from './client'
import type { ScreenSnapshot } from './types'

/** 大屏只读授权：token 只经 Authorization 请求头发送，不进入 URL 查询参数或本地存储。 */
export function screenApi(grantId: string, token: string) {
  const client = createClient({ bearer: () => token })
  return {
    snapshot: (signal?: AbortSignal) =>
      client.get<ScreenSnapshot>(`/screens/${encodeURIComponent(grantId)}/snapshot`, { signal }),
  }
}
