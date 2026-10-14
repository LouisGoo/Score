/**
 * 服务端时钟偏差：以响应中的 server_time 减去本机收到响应的时间。
 * 倒计时据此在本地推算，不每秒请求服务端；截止以服务端锁内校验为准。
 */
export function clockOffset(serverTime: string, receivedAt: number = Date.now()): number {
  return Date.parse(serverTime) - receivedAt
}

export function serverNow(offsetMs: number, now: number = Date.now()): number {
  return now + offsetMs
}

/** 剩余毫秒数；不限时返回 null，已截止返回 0。 */
export function remainingMs(deadlineAt: string | null, offsetMs: number, now: number = Date.now()): number | null {
  if (deadlineAt === null) return null
  return Math.max(0, Date.parse(deadlineAt) - serverNow(offsetMs, now))
}

/** 暂停时服务端返回十进制剩余秒数（精确到微秒），转换为毫秒。 */
export function pausedRemainingMs(remainingSeconds: string | null): number | null {
  if (remainingSeconds === null) return null
  return Math.max(0, Math.round(Number(remainingSeconds) * 1000))
}

/** 倒计时显示，向上取整到秒，避免提前显示为 0。 */
export function formatCountdown(ms: number | null): string {
  if (ms === null) return '不限时'
  const total = Math.ceil(ms / 1000)
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}
