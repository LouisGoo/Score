import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { judgeApi, judgeScoring } from '../api/judge'
import { ApiError } from '../api/client'
import { queryKeys } from '../api/query'
import type { BallotReceipt, JudgeSnapshot } from '../api/types'
import { clockOffset } from '../lib/clock'
import { preferNewer } from '../lib/polling'
import { useRealtime } from '../lib/useRealtime'

export type MobileSnapshot = JudgeSnapshot & { offsetMs: number }
export function useJudgeSnapshot(eventId: string, judgeId: string) {
  const client = useQueryClient()
  const key = queryKeys.judgeSnapshot(judgeId, eventId)
  const query = useQuery({
    queryKey: key,
    queryFn: async ({ signal }): Promise<MobileSnapshot> => {
      const next = await judgeScoring.snapshot(eventId, signal)
      if (next.identity.id !== judgeId || next.event.id !== eventId) {
        throw new ApiError(401, 'SESSION_EXPIRED', '评委身份已变化，请重新确认身份')
      }
      return preferNewer(client.getQueryData<MobileSnapshot>(key), { ...next, offsetMs: clockOffset(next.server_time) })
    },
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })
  const sync = useRealtime({ key, role: 'judge', eventId, api: judgeApi, refetch: query.refetch })
  const error = sync.error ?? query.error
  const invalid = error instanceof ApiError && [401, 403, 404].includes(error.status)
  return { ...query, error, data: invalid ? undefined : query.data, publicCode: query.data?.event.public_code,
    isError: !!error, isPending: invalid ? false : query.isPending,
    syncStatus: sync.status, verifiedAt: Math.max(sync.verifiedAt, query.dataUpdatedAt) }
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
