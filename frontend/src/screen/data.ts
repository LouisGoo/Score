import { useEffect, useId, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { screenApi } from '../api/screen'
import { ApiError } from '../api/client'
import { queryKeys } from '../api/query'
import type { ScreenSnapshot } from '../api/types'
import { clockOffset } from '../lib/clock'
import { jittered, POLL_INTERVAL_MS, preferNewer } from '../lib/polling'

export type DisplaySnapshot = ScreenSnapshot & { offsetMs: number }
export function invalidGrant(error: unknown): boolean {
  return error instanceof ApiError && (error.code === 'SCREEN_GRANT_INVALID' || [401, 403, 404].includes(error.status))
}

export function useScreenSnapshot(grantId: string, token: string) {
  const client = useQueryClient()
  // An instance discriminator prevents reusing data from a different token for the same grant ID.
  const instance = useId()
  const key = useMemo(() => [...queryKeys.screenSnapshot(grantId), instance], [grantId, instance])
  const query = useQuery({
    queryKey: key,
    queryFn: async ({ signal }): Promise<DisplaySnapshot> => {
      const next = await screenApi(grantId, token).snapshot(signal)
      return preferNewer(client.getQueryData<DisplaySnapshot>(key), { ...next, offsetMs: clockOffset(next.server_time) })
    },
    refetchInterval: q => invalidGrant(q.state.error) ? false : Math.max(jittered(POLL_INTERVAL_MS.screen),
      q.state.error instanceof ApiError ? (q.state.error.retryAfter ?? 0) * 1000 : 0),
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
    gcTime: 0,
  })
  useEffect(() => () => {
    void client.cancelQueries({ queryKey: key })
    client.removeQueries({ queryKey: key })
  }, [client, key])
  return query
}
