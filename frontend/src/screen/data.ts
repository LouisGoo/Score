import { useEffect, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { screenApi } from '../api/screen'
import { ApiError, createClient } from '../api/client'
import { queryKeys } from '../api/query'
import type { ScreenSnapshot } from '../api/types'
import { clockOffset } from '../lib/clock'
import { jittered, preferNewer } from '../lib/polling'
import { useRealtime } from '../lib/useRealtime'

let nextScreenInstance = 0

export type DisplaySnapshot = ScreenSnapshot & { offsetMs: number }
export function invalidGrant(error: unknown): boolean {
  return error instanceof ApiError && (error.code === 'SCREEN_GRANT_INVALID' || [401, 403, 404].includes(error.status))
}

export function useScreenSnapshot(grantId: string, token: string) {
  const client = useQueryClient()
  // An instance discriminator prevents reusing data from a different token for the same grant ID.
  const scope = useMemo(() => ({ grantId, token, instance: ++nextScreenInstance }), [grantId, token])
  const instance = scope.instance
  const key = useMemo(() => [...queryKeys.screenSnapshot(grantId), instance], [grantId, instance])
  const query = useQuery({
    queryKey: key,
    queryFn: async ({ signal }): Promise<DisplaySnapshot> => {
      const next = await screenApi(grantId, token).snapshot(signal)
      return preferNewer(client.getQueryData<DisplaySnapshot>(key), { ...next, offsetMs: clockOffset(next.server_time) })
    },
    retry: false,
    refetchInterval: q => q.state.data || invalidGrant(q.state.error) ? false : Math.max(
      jittered(Math.min(60_000, 5000 * 2 ** Math.min(4, q.state.errorUpdateCount))),
      q.state.error instanceof ApiError ? (q.state.error.retryAfter ?? 0) * 1000 : 0),
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    gcTime: 0,
  })
  useEffect(() => () => {
    void client.cancelQueries({ queryKey: key })
    client.removeQueries({ queryKey: key })
  }, [client, key])
  const sync = useRealtime({ key, role: 'screen', eventId: query.data?.event.id, grantId,
    api: createClient({ bearer: () => token }), refetch: query.refetch })
  const error = sync.error ?? query.error
  return { ...query, error, data: invalidGrant(error) ? undefined : query.data,
    isError: !!error, isPending: invalidGrant(error) ? false : query.isPending,
    syncStatus: sync.status, verifiedAt: Math.max(sync.verifiedAt, query.dataUpdatedAt) }
}
