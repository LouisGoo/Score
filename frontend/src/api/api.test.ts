import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { adminApi, adminAuth } from './admin'
import { ApiError, createClient, request } from './client'
import { describeError, knownErrorCodes } from './errors'
import { judgeAuth } from './judge'
import { retryDelay, shouldRetryQuery } from './query'
import { screenApi } from './screen'

type Reply = { status?: number; body?: unknown; headers?: Record<string, string> }

function json({ status = 200, body, headers = {} }: Reply): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', 'X-Request-ID': 'r'.repeat(32), ...headers },
  })
}

/** 按顺序返回预设响应，并记录每次请求的路径、方法和请求头。 */
function mockFetch(...replies: (Reply | Error)[]) {
  const calls: { path: string; method: string; headers: Record<string, string>; body: unknown }[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    calls.push({
      path: String(input),
      method: init.method ?? 'GET',
      headers: (init.headers ?? {}) as Record<string, string>,
      body: init.body ? JSON.parse(String(init.body)) : undefined,
    })
    const reply = replies.shift()
    if (!reply) throw new Error('unexpected request')
    if (reply instanceof Error) throw reply
    return json(reply)
  })
  vi.stubGlobal('fetch', fetchMock)
  return calls
}

const error = (code: string, status = 409, headers: Record<string, string> = {}): Reply => ({
  status,
  body: { error: { code, message: `服务端：${code}` }, request_id: 'r'.repeat(32) },
  headers,
})

describe('request', () => {
  it('calls same-origin /api/v1 without caching and parses JSON', async () => {
    const calls = mockFetch({ body: { status: 'ok' } })
    await expect(request('/health/live')).resolves.toEqual({ status: 'ok' })
    expect(calls[0].path).toBe('/api/v1/health/live')
    const init = vi.mocked(fetch).mock.calls[0][1]!
    expect(init.credentials).toBe('same-origin')
    expect(init.cache).toBe('no-store')
  })

  it('returns undefined for 204', async () => {
    mockFetch({ status: 204 })
    await expect(request('/x', { method: 'DELETE' })).resolves.toBeUndefined()
  })

  it('converts the error envelope including request id and Retry-After', async () => {
    mockFetch(error('SERVICE_UNAVAILABLE', 503, { 'Retry-After': '3' }))
    const failure = await request('/x').catch((e: unknown) => e)
    expect(failure).toBeInstanceOf(ApiError)
    expect(failure).toMatchObject({ status: 503, code: 'SERVICE_UNAVAILABLE', requestId: 'r'.repeat(32), retryAfter: 3 })
    expect((failure as ApiError).outcomeUnknown).toBe(false)
  })

  it('keeps well-formed validation issues from the error envelope', async () => {
    const issue = { code: 'ENTRIES_REQUIRED', message: '至少需要一个参评对象', field: 'entries' }
    mockFetch({
      status: 422,
      body: { error: { code: 'PUBLISH_INVALID', message: '发布检查未通过', issues: [issue, { code: 1 }] }, request_id: 'r'.repeat(32) },
    })
    const failure = (await request('/x').catch((e: unknown) => e)) as ApiError
    expect(failure).toMatchObject({ status: 422, code: 'PUBLISH_INVALID', issues: [issue] })

    mockFetch(error('NOT_FOUND', 404))
    expect(((await request('/x').catch((e: unknown) => e)) as ApiError).issues).toEqual([])
  })

  it('handles non-JSON error pages', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>bad gateway</html>', { status: 502 })))
    await expect(request('/x')).rejects.toMatchObject({ status: 502, code: 'HTTP_ERROR' })
  })

  it('marks network failures and timeouts as outcome unknown', async () => {
    mockFetch(new TypeError('Failed to fetch'))
    const failure = (await request('/x').catch((e: unknown) => e)) as ApiError
    expect(failure).toMatchObject({ status: 0, code: 'NETWORK_ERROR' })
    expect(failure.outcomeUnknown).toBe(true)

    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_: RequestInfo | URL, init: RequestInit = {}) =>
          new Promise<Response>((_resolve, reject) => {
            init.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
          }),
      ),
    )
    await expect(request('/x', { timeoutMs: 10 })).rejects.toMatchObject({ status: 0, code: 'TIMEOUT' })
  })

  it('propagates caller aborts as AbortError instead of a network failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_: RequestInfo | URL, init: RequestInit = {}) =>
          new Promise<Response>((_resolve, reject) => {
            init.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
          }),
      ),
    )
    const controller = new AbortController()
    const pending = request('/x', { signal: controller.signal })
    controller.abort()
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  })
})

describe('createClient', () => {
  it('sends CSRF only on writes and Bearer on every request', async () => {
    const calls = mockFetch({ body: {} }, { body: {} })
    const client = createClient({ csrf: { get: () => 'csrf-1' }, bearer: () => 'grant-token' })
    await client.get('/a')
    await client.send('POST', '/b', { x: 1 })
    expect(calls[0].headers).toEqual({ Authorization: 'Bearer grant-token' })
    expect(calls[1].headers).toMatchObject({ Authorization: 'Bearer grant-token', 'X-CSRF-Token': 'csrf-1', 'Content-Type': 'application/json' })
    expect(calls[1].body).toEqual({ x: 1 })
  })

  it('refreshes CSRF and retries exactly once on CSRF_INVALID', async () => {
    let token = 'stale'
    const refresh = vi.fn(async () => {
      token = 'fresh'
    })
    const calls = mockFetch(error('CSRF_INVALID', 403), { body: { ok: true } })
    const client = createClient({ csrf: { get: () => token, refresh } })
    await expect(client.send('POST', '/b')).resolves.toEqual({ ok: true })
    expect(refresh).toHaveBeenCalledOnce()
    expect(calls.map(c => c.headers['X-CSRF-Token'])).toEqual(['stale', 'fresh'])

    mockFetch(error('CSRF_INVALID', 403), error('CSRF_INVALID', 403))
    await expect(client.send('POST', '/b')).rejects.toMatchObject({ code: 'CSRF_INVALID' })
  })

  it('never retries other failures automatically', async () => {
    const calls = mockFetch(error('VERSION_CONFLICT'))
    const client = createClient({ csrf: { get: () => 't', refresh: vi.fn() } })
    await expect(client.send('POST', '/rounds/r/open', { expected_version: 1 })).rejects.toMatchObject({ code: 'VERSION_CONFLICT' })
    expect(calls).toHaveLength(1)
  })
})

describe('admin session', () => {
  beforeEach(() => adminAuth.forget())

  it('logs in with the pre-login CSRF and then uses the session CSRF', async () => {
    const session = { admin: { id: 'a1', login: 'host' }, expires_at: '2026-10-14T08:00:00Z', csrf_token: 'session-csrf' }
    const calls = mockFetch({ body: { csrf_token: 'login-csrf' } }, { body: session }, { status: 204 })
    await adminAuth.login('host', 'secret-password')
    await adminAuth.logout()
    expect(calls.map(c => [c.method, c.path, c.headers['X-CSRF-Token']])).toEqual([
      ['GET', '/api/v1/auth/csrf', undefined],
      ['POST', '/api/v1/auth/login', 'login-csrf'],
      ['POST', '/api/v1/auth/logout', 'session-csrf'],
    ])
    expect(JSON.stringify(localStorage)).not.toContain('csrf')
  })

  it('restores CSRF through /auth/me and clears it after logout even on failure', async () => {
    const calls = mockFetch(
      { body: { admin: {}, expires_at: '', csrf_token: 'restored' } },
      { body: {} },
      error('SESSION_EXPIRED', 401),
      { body: {} },
    )
    await adminAuth.me()
    await adminApi.send('PATCH', '/events/e1', { title: 'x' })
    await expect(adminAuth.logout()).rejects.toMatchObject({ code: 'SESSION_EXPIRED' })
    await adminApi.send('PATCH', '/events/e1', { title: 'y' })
    expect(calls[1].headers['X-CSRF-Token']).toBe('restored')
    expect(calls[3].headers['X-CSRF-Token']).toBeUndefined()
  })
})

describe('judge session', () => {
  beforeEach(() => judgeAuth.forget())

  it('uses bootstrap CSRF for verify/exchange and session CSRF afterwards', async () => {
    const calls = mockFetch(
      { body: { csrf_token: 'bootstrap' } },
      { body: { judge: { id: 'j1' }, confirmation_token: 'confirm', expires_at: '' } },
      { body: { judge: { id: 'j1' }, expires_at: '', csrf_token: 'judge-session', read_only: false } },
      { status: 204 },
    )
    await judgeAuth.verify('ABCDEFGH2345', 'FIRST123')
    await judgeAuth.exchange('confirm')
    await judgeAuth.logout()
    expect(calls.map(c => [c.path, c.headers['X-CSRF-Token']])).toEqual([
      ['/api/v1/judge-sessions/csrf', undefined],
      ['/api/v1/judge-sessions/verify', 'bootstrap'],
      ['/api/v1/judge-sessions/exchange', 'bootstrap'],
      ['/api/v1/judge-sessions/logout', 'judge-session'],
    ])
    expect(calls[1].body).toEqual({ public_code: 'ABCDEFGH2345', code: 'FIRST123' })
  })

  it('re-bootstraps when the bootstrap cookie has expired', async () => {
    const calls = mockFetch(
      { body: { csrf_token: 'old' } },
      error('CSRF_INVALID', 403),
      { body: { csrf_token: 'new' } },
      { body: { confirmation_token: 'c' } },
    )
    await judgeAuth.verify('ABCDEFGH2345', 'FIRST123')
    expect(calls.map(c => c.headers['X-CSRF-Token'] ?? c.path)).toEqual(['/api/v1/judge-sessions/csrf', 'old', '/api/v1/judge-sessions/csrf', 'new'])
  })

  it('normalizes the public code in the preview path', async () => {
    const calls = mockFetch({ body: {} })
    await judgeAuth.preview(' abcdefgh2345 ')
    expect(calls[0].path).toBe('/api/v1/join/ABCDEFGH2345')
  })
})

describe('screen client', () => {
  it('sends the grant token only as a Bearer header', async () => {
    const calls = mockFetch({ body: { version: 1 } })
    await screenApi('grant/1', 'secret-token').snapshot()
    expect(calls[0].path).toBe('/api/v1/screens/grant%2F1/snapshot')
    expect(calls[0].path).not.toContain('secret-token')
    expect(calls[0].headers).toEqual({ Authorization: 'Bearer secret-token' })
  })
})

function pythonFiles(dir: string): string[] {
  return readdirSync(dir).flatMap(name => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return name === '__pycache__' ? [] : pythonFiles(path)
    return path.endsWith('.py') ? [path] : []
  })
}

describe('errors', () => {
  it('maps every error code raised by the backend', () => {
    // vitest 从 frontend 目录运行；jsdom 环境下 import.meta.url 不是 file: 地址。
    const backend = resolve(process.cwd(), '../backend/src/score_api')
    const raised = new Set<string>()
    for (const file of pythonFiles(backend)) {
      for (const match of readFileSync(file, 'utf8').matchAll(/APIError\(\s*\d{3},\s*"([A-Z_]+)"/g)) raised.add(match[1])
    }
    expect(raised.size).toBeGreaterThan(30)
    expect([...raised].filter(code => !knownErrorCodes.includes(code))).toEqual([])
  })

  it('prefers the server message and keeps request id for support', () => {
    const description = describeError(new ApiError(409, 'VERSION_CONFLICT', '活动版本已变化', 'req-1'))
    expect(description).toMatchObject({ action: 'refresh', message: '活动版本已变化', requestId: 'req-1' })
    expect(description.hint).toBeTruthy()
  })

  it('stops on unknown codes and non-API errors', () => {
    expect(describeError(new ApiError(418, 'NEW_CODE', '')).action).toBe('stop')
    expect(describeError(new Error('boom'))).toMatchObject({ code: 'UNKNOWN', action: 'stop' })
    expect(describeError(new ApiError(0, 'TIMEOUT', '请求超时')).action).toBe('verify')
  })
})

describe('query retry policy', () => {
  it('retries reads only for network errors and 503, at most twice', () => {
    expect(shouldRetryQuery(0, new ApiError(0, 'NETWORK_ERROR', ''))).toBe(true)
    expect(shouldRetryQuery(1, new ApiError(503, 'SERVICE_UNAVAILABLE', ''))).toBe(true)
    expect(shouldRetryQuery(2, new ApiError(503, 'SERVICE_UNAVAILABLE', ''))).toBe(false)
    expect(shouldRetryQuery(0, new ApiError(401, 'SESSION_EXPIRED', ''))).toBe(false)
    expect(shouldRetryQuery(0, new ApiError(409, 'VERSION_CONFLICT', ''))).toBe(false)
  })

  it('honours Retry-After before exponential backoff', () => {
    expect(retryDelay(0, new ApiError(503, 'X', '', null, 3))).toBe(3000)
    expect(retryDelay(1, new ApiError(0, 'X', ''))).toBe(2000)
    expect(retryDelay(10, new ApiError(0, 'X', ''))).toBe(8000)
  })
})
