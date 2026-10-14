import { useEffect, useState } from 'react'

/** 本机当前时间，active 时按间隔刷新，用于本地推算倒计时；不触发任何请求。 */
export function useNow(active: boolean, intervalMs = 500): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const timer = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(timer)
  }, [active, intervalMs])
  return now
}
