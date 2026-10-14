import type { LoaderFunctionArgs } from 'react-router'

export interface ScreenAccess { grantId: string; token: string | null }

/** Read once before React renders (including StrictMode); nothing is stored outside router memory. */
export function screenLoader({ params }: LoaderFunctionArgs): ScreenAccess {
  const hash = window.location.hash.slice(1)
  const token = hash.startsWith('token=') ? new URLSearchParams(hash).get('token') : hash
  if (hash) window.history.replaceState(window.history.state, '', window.location.pathname + window.location.search)
  return { grantId: params.grantId ?? '', token: token && /^[A-Za-z0-9_-]{43}$/.test(token) ? token : null }
}
