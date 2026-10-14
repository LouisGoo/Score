/**
 * 实时推送（18）之前的快照轮询间隔。页面不可见时暂停，回到前台立即刷新；
 * 带随机抖动，避免大量手机同时回源。实际间隔以容量测试结果为准。
 */
export const POLL_INTERVAL_MS = {
  admin: 3000,
  screen: 3000,
  judge: 5000,
} as const

export function jittered(baseMs: number, ratio = 0.2, random: () => number = Math.random): number {
  return Math.round(baseMs * (1 - ratio + 2 * ratio * random()))
}

/** TanStack Query 轮询选项：后台标签页不轮询，聚焦和重连时刷新。 */
export function pollingOptions(baseMs: number) {
  return {
    refetchInterval: () => jittered(baseMs),
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  }
}

interface Versioned {
  version: number
}

/**
 * 快照版本只增不减；较旧版本的响应（乱序到达）不覆盖已显示的状态。
 * 相同版本仍采用新响应，以刷新 server_time 等时钟信息。
 * 仅适用于同一缓存键（同一角色、身份和活动）内比较。
 */
export function preferNewer<T extends Versioned>(previous: T | undefined, next: T): T {
  return previous !== undefined && next.version < previous.version ? previous : next
}
