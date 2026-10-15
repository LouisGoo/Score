import { ApiError } from '../api/client'
import { jittered } from './polling'

export type SyncStatus = 'connecting' | 'recovering' | 'live' | 'polling' | 'offline' | 'paused' | 'expired'
export interface Ticket { ticket: string; stream_path: string }
export interface SyncOptions {
  eventId: string
  role: 'admin' | 'judge' | 'screen'
  ticket(signal: AbortSignal): Promise<Ticket>
  version(signal: AbortSignal): Promise<number>
  snapshot(): Promise<number>
  currentVersion(): number
  socket(path: string): WebSocket
  status(value: SyncStatus): void
  verified(): void
  invalid(error: ApiError): void
}

/** 消息只作为快照失效通知，因此缓冲只需保存最大版本，内存不会随事件数增长。 */
export class RealtimeSync {
  private ws: WebSocket | null = null
  private abort = new AbortController()
  private timers = new Set<ReturnType<typeof setTimeout>>()
  private refreshTimer: ReturnType<typeof setTimeout> | undefined
  private transportTimer: ReturnType<typeof setTimeout> | undefined
  private checkTimer: ReturnType<typeof setTimeout> | undefined
  private pollingTimer: ReturnType<typeof setTimeout> | undefined
  private epoch = 0
  private transportEpoch = 0
  private active = false
  private live = false
  private connecting = false
  private failures = 0
  private pollFailures = 0
  private wanted = -1
  private inflight: Promise<void> | null = null
  private force = false
  private pollNotBefore = 0
  private retryNotBefore = 0

  constructor(private options: SyncOptions) {}

  private later(fn: () => void, ms: number) {
    const timer = setTimeout(() => { this.timers.delete(timer); fn() }, ms)
    this.timers.add(timer)
    return timer
  }
  private clear(timer: ReturnType<typeof setTimeout> | undefined) {
    if (timer !== undefined) { clearTimeout(timer); this.timers.delete(timer) }
  }
  private closeSocket() {
    this.transportEpoch++
    const previous = this.ws
    this.ws = null
    previous?.close()
    this.clear(this.transportTimer)
    this.clear(this.checkTimer)
    this.connecting = this.live = false
  }
  pause(status: SyncStatus = 'paused') {
    this.active = false
    this.epoch++
    this.abort.abort()
    this.abort = new AbortController()
    this.closeSocket()
    for (const timer of this.timers) clearTimeout(timer)
    this.timers.clear()
    this.refreshTimer = this.pollingTimer = undefined
    this.options.status(status)
  }
  resume(refresh = true) {
    this.pause('connecting')
    this.active = true
    // 前台恢复立即核验 HTTP；WS ready 后还会在缓冲开启的情况下再次读快照。
    this.retryNotBefore = this.pollNotBefore = 0
    if (refresh) void this.refresh(true)
    void this.connect()
    this.schedulePoll()
  }
  stop() { this.pause('paused') }

  private fatal(error: unknown): boolean {
    if (error instanceof ApiError && [401, 403, 404].includes(error.status)) {
      this.pause('expired')
      this.options.invalid(error)
      return true
    }
    return false
  }
  private schedulePoll(retryAfter = 0) {
    if (!this.active || this.live) return
    this.pollNotBefore = Math.max(this.pollNotBefore, Date.now() + retryAfter)
    if (this.pollingTimer !== undefined && retryAfter === 0) return
    this.clear(this.pollingTimer)
    const delay = Math.max(jittered(Math.min(60_000, 5000 * 2 ** Math.min(4, this.pollFailures))), this.pollNotBefore - Date.now())
    this.pollingTimer = this.later(() => { this.pollingTimer = undefined; void this.refresh(true) }, delay)
  }
  private failed(error?: unknown) {
    if (!this.active || this.fatal(error)) return
    this.closeSocket()
    this.options.status('polling')
    this.failures++
    const retryAfter = error instanceof ApiError ? (error.retryAfter ?? 0) * 1000 : 0
    this.schedulePoll(retryAfter)
    this.transportTimer = this.later(() => { void this.connect() },
      Math.max(jittered(Math.min(30_000, 1000 * 2 ** Math.min(5, this.failures - 1))), retryAfter))
  }
  private watchdog(delay = 45_000) {
    this.clear(this.transportTimer)
    this.transportTimer = this.later(() => this.failed(), delay)
  }
  private async connect() {
    if (!this.active || this.connecting || this.ws) return
    const epoch = this.epoch
    this.connecting = true
    const transportEpoch = ++this.transportEpoch
    try {
      const ticket = await this.options.ticket(this.abort.signal)
      if (!this.active || epoch !== this.epoch || transportEpoch !== this.transportEpoch) return
      const ws = this.ws = this.options.socket(ticket.stream_path)
      this.watchdog(10_000)
      ws.addEventListener('open', () => { if (this.ws === ws) ws.send(JSON.stringify({ ticket: ticket.ticket })) })
      ws.addEventListener('close', () => { if (this.ws === ws) this.failed() })
      ws.addEventListener('error', () => { if (this.ws === ws) this.failed() })
      ws.addEventListener('message', event => {
        if (this.ws !== ws || !this.active) return
        let message: Record<string, unknown>
        try { message = JSON.parse(String(event.data)) }
        catch { this.failed(); return }
        if (!message || typeof message !== 'object') { this.failed(); return }
        this.watchdog()
        if (message.type === 'session.revoked') {
          this.fatal(new ApiError(401, 'SESSION_EXPIRED', '授权已失效，请重新验证身份'))
          return
        }
        if (message.type === 'stream.heartbeat') return
        if (message.event_id !== this.options.eventId) return
        if (message.type === 'stream.ready') {
          this.connecting = false
          this.live = true
          this.failures = 0
          this.clear(this.pollingTimer)
          this.pollingTimer = undefined
          this.options.status('recovering')
          void this.refresh(true)
          this.scheduleCheck()
        } else if (message.type === 'stream.resync') {
          void this.refresh(true)
        } else if (message.scope === this.options.role && Number.isSafeInteger(message.version) &&
          Number(message.version) > this.options.currentVersion()) {
          this.wanted = Math.max(this.wanted, Number(message.version))
          // 连续消息、跳号和乱序统一合并回源；HTTP 快照覆盖缓冲的所有已提交版本。
          if (this.refreshTimer === undefined) {
            this.refreshTimer = this.later(() => { this.refreshTimer = undefined; void this.refresh() }, 100)
          }
        }
      })
    } catch (error) {
      if (this.active && epoch === this.epoch && transportEpoch === this.transportEpoch) this.failed(error)
    }
  }
  private scheduleCheck() {
    this.clear(this.checkTimer)
    if (!this.active || !this.live) return
    this.checkTimer = this.later(() => { void this.check() }, jittered(30_000, 0.1))
  }
  private async check() {
    const epoch = this.epoch
    try {
      const version = await this.options.version(this.abort.signal)
      if (!this.active || epoch !== this.epoch) return
      if (version > this.options.currentVersion()) {
        this.wanted = Math.max(this.wanted, version)
        await this.refresh()
      } else {
        this.options.verified()
      }
      this.scheduleCheck()
    } catch (error) {
      if (this.active && epoch === this.epoch) this.failed(error)
    }
  }
  private refresh(force = false): Promise<void> {
    this.force ||= force
    if (Date.now() < this.retryNotBefore) {
      if (this.refreshTimer === undefined) {
        this.refreshTimer = this.later(() => { this.refreshTimer = undefined; void this.refresh() }, this.retryNotBefore - Date.now())
      }
      return Promise.resolve()
    }
    if (!this.active) return Promise.resolve()
    if (this.inflight) return this.inflight
    const epoch = this.epoch
    this.inflight = (async () => {
      // 至多连续读两次；若落后的读视图仍未覆盖缓冲，稍后重试，避免回源热循环。
      for (let attempt = 0; attempt < 2 && this.active; attempt++) {
        if (!this.force && this.wanted <= this.options.currentVersion()) break
        this.force = false
        try {
          await this.options.snapshot()
          if (!this.active || epoch !== this.epoch) return
          this.pollFailures = 0
          this.retryNotBefore = this.pollNotBefore = 0
          this.options.verified()
          if (this.live) this.options.status('live')
        } catch (error) {
          if (!this.active || epoch !== this.epoch || this.fatal(error)) return
          this.pollFailures++
          const retryAfter = error instanceof ApiError ? (error.retryAfter ?? 0) * 1000 : 0
          this.retryNotBefore = Date.now() + Math.max(retryAfter, jittered(Math.min(60_000, 5000 * 2 ** Math.min(4, this.pollFailures))))
          this.failed(error)
          this.schedulePoll(retryAfter)
          return
        }
      }
    })().finally(() => {
      this.inflight = null
      if (!this.active) return
      if (this.force || this.wanted > this.options.currentVersion()) {
        this.clear(this.refreshTimer)
        this.refreshTimer = this.later(() => { this.refreshTimer = undefined; void this.refresh() }, Math.max(1000, this.retryNotBefore - Date.now()))
      }
      this.schedulePoll()
    })
    return this.inflight
  }
}

