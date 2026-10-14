/**
 * 读取 URL fragment 中的凭证（如私人邀请的身份码、大屏 token）并立即从地址栏清除，
 * 避免留在浏览历史、截图或被复制转发。fragment 不会随请求发送到服务端。
 */
export function takeFragmentParams<K extends string>(keys: readonly K[]): Partial<Record<K, string>> {
  const hash = window.location.hash.replace(/^#/, '')
  if (!hash) return {}
  const params = new URLSearchParams(hash)
  const result: Partial<Record<K, string>> = {}
  for (const key of keys) {
    const value = params.get(key)
    if (value) result[key] = value
  }
  const { pathname, search } = window.location
  window.history.replaceState(window.history.state, '', pathname + search)
  return result
}

export function fragmentUrl(base: string, path: string, params: Record<string, string>): string {
  return `${base.replace(/\/$/, '')}${path}#${new URLSearchParams(params).toString()}`
}

/** 二维码与邀请链接的对外地址；部署时由构建变量指定，开发期回退为当前站点。 */
export function publicBaseUrl(): string {
  return import.meta.env.VITE_PUBLIC_BASE_URL || window.location.origin
}
