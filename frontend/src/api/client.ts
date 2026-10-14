export const API_PREFIX = '/api/v1'
const DEFAULT_TIMEOUT_MS = 15_000

/** 业务校验问题（如发布检查）；field 为点分隔定位，数组索引从 0 开始。 */
export interface ApiIssue {
  code: string
  message: string
  field: string
}

/** 统一的接口错误；status 为 0 表示请求未得到服务端响应，结果可能未知。 */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly requestId: string | null
  readonly retryAfter: number | null
  readonly issues: ApiIssue[]

  constructor(
    status: number,
    code: string,
    message: string,
    requestId: string | null = null,
    retryAfter: number | null = null,
    issues: ApiIssue[] = [],
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.requestId = requestId
    this.retryAfter = retryAfter
    this.issues = issues
  }

  /** 请求是否可能已在服务端生效（超时或连接中断）；此时不能直接判定失败。 */
  get outcomeUnknown(): boolean {
    return this.status === 0
  }
}

export type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

export interface RequestOptions {
  method?: Method
  body?: unknown
  headers?: Record<string, string>
  signal?: AbortSignal
  timeoutMs?: number
}

function retryAfterSeconds(response: Response): number | null {
  const value = Number(response.headers.get('Retry-After'))
  return Number.isFinite(value) && value > 0 ? value : null
}

function parseIssues(value: unknown): ApiIssue[] {
  if (!Array.isArray(value)) return []
  return value.filter(
    (item): item is ApiIssue =>
      !!item && typeof item.code === 'string' && typeof item.message === 'string' && typeof item.field === 'string',
  )
}

async function toApiError(response: Response): Promise<ApiError> {
  const requestId = response.headers.get('X-Request-ID')
  let code = 'HTTP_ERROR'
  let message = '请求无法处理'
  let issues: ApiIssue[] = []
  try {
    const body: unknown = await response.json()
    if (body && typeof body === 'object' && 'error' in body) {
      const error = (body as { error: { code?: unknown; message?: unknown; issues?: unknown } }).error
      if (typeof error.code === 'string') code = error.code
      if (typeof error.message === 'string') message = error.message
      issues = parseIssues(error.issues)
    }
  } catch {
    // 非 JSON 响应（如代理错误页）按通用错误处理。
  }
  return new ApiError(response.status, code, message, requestId, retryAfterSeconds(response), issues)
}

/** 同源调用 /api/v1；不自动重试，重试策略由调用方按操作是否幂等决定。 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, headers = {}, signal, timeoutMs = DEFAULT_TIMEOUT_MS } = options
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  const abort = () => controller.abort()
  signal?.addEventListener('abort', abort, { once: true })
  let response: Response
  try {
    response = await fetch(API_PREFIX + path, {
      method,
      credentials: 'same-origin',
      cache: 'no-store',
      signal: controller.signal,
      headers: body === undefined ? headers : { 'Content-Type': 'application/json', ...headers },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    const timedOut = controller.signal.aborted
    throw new ApiError(0, timedOut ? 'TIMEOUT' : 'NETWORK_ERROR', timedOut ? '请求超时' : '网络连接失败')
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', abort)
  }
  if (!response.ok) throw await toApiError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export interface CsrfSource {
  /** 当前可用的 CSRF 令牌；没有时写请求直接发送，由服务端拒绝。 */
  get(): string | null
  /** CSRF 失效后刷新；请求在业务处理前即被拒绝，因此允许刷新后重试一次。 */
  refresh?(): Promise<void>
}

export interface Client {
  get<T>(path: string, options?: Omit<RequestOptions, 'method' | 'body'>): Promise<T>
  send<T>(method: Exclude<Method, 'GET'>, path: string, body?: unknown, options?: Omit<RequestOptions, 'method' | 'body'>): Promise<T>
}

/** 按身份创建客户端：写请求附带该身份的 CSRF，或在每个请求附带 Bearer 授权。 */
export function createClient(auth: { csrf?: CsrfSource; bearer?: () => string | null }): Client {
  function headersFor(write: boolean, extra: Record<string, string> = {}) {
    const headers: Record<string, string> = { ...extra }
    const bearer = auth.bearer?.()
    if (bearer) headers.Authorization = `Bearer ${bearer}`
    const csrf = write ? auth.csrf?.get() : null
    if (csrf) headers['X-CSRF-Token'] = csrf
    return headers
  }

  return {
    get: (path, options = {}) => request(path, { ...options, headers: headersFor(false, options.headers) }),
    async send(method, path, body, options = {}) {
      const run = () => request<never>(path, { ...options, method, body, headers: headersFor(true, options.headers) })
      try {
        return await run()
      } catch (error) {
        if (!(error instanceof ApiError) || error.code !== 'CSRF_INVALID' || !auth.csrf?.refresh) throw error
        await auth.csrf.refresh()
        return await run()
      }
    },
  }
}

/** 仅存于内存的令牌；刷新页面后通过 me 接口恢复，不写入本地存储。 */
export function memoryToken() {
  let value: string | null = null
  return {
    get: () => value,
    set: (next: string | null) => {
      value = next
    },
  }
}
