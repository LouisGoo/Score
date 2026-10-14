import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { judgeScoring } from '../api/judge'
import { ApiError } from '../api/client'
import { queryKeys } from '../api/query'
import type { BallotReceipt, JudgeSnapshot } from '../api/types'
import { clockOffset } from '../lib/clock'
import { jittered, POLL_INTERVAL_MS, preferNewer } from '../lib/polling'

export type MobileSnapshot = JudgeSnapshot & { offsetMs: number }
export function useJudgeSnapshot(eventId: string, judgeId: string) {
  const client = useQueryClient()
  const key = queryKeys.judgeSnapshot(judgeId, eventId)
  return useQuery({
    queryKey: key,
    queryFn: async ({ signal }): Promise<MobileSnapshot> => {
      const next = await judgeScoring.snapshot(eventId, signal)
      if (next.identity.id !== judgeId || next.event.id !== eventId) {
        throw new ApiError(401, 'SESSION_EXPIRED', '评委身份已变化，请重新确认身份')
      }
      return preferNewer(client.getQueryData<MobileSnapshot>(key), { ...next, offsetMs: clockOffset(next.server_time) })
    },
    refetchInterval: query => {
      const status = query.state.data?.event.status
      if (status === 'FINISHED' || status === 'ARCHIVED') return false
      // Do not hammer a service that has requested a backoff after retries are exhausted.
      const error = query.state.error as { retryAfter?: number } | null
      return Math.max(jittered(POLL_INTERVAL_MS.judge), (error?.retryAfter ?? 0) * 1000)
    },
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
  })
}

export function receiptsFor(snapshot: JudgeSnapshot, roundId: string): BallotReceipt[] {
  // ES2022 phone baseline; sorting the newly filtered array does not mutate the snapshot.
  const receipts = snapshot.my_ballots.filter(b => b.judge_id === snapshot.identity.id)
    .flatMap(b => b.receipts).filter(r => r.round_id === roundId)
  // oxlint-disable-next-line unicorn/no-array-sort
  return receipts.sort((a, b) => b.revision - a.revision)
}

/** Online is only a hint; a successful fresh snapshot is still required before confirmation. */
export function useOnline() {
  const [online, setOnline] = useState(navigator.onLine)
  useEffect(() => {
    const update = () => setOnline(navigator.onLine)
    window.addEventListener('online', update)
    window.addEventListener('offline', update)
    return () => {
      window.removeEventListener('online', update)
      window.removeEventListener('offline', update)
    }
  }, [])
  return online
}
