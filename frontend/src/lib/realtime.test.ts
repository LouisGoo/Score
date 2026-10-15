import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { RealtimeSync, type SyncOptions } from './realtime'

class Socket extends EventTarget {
  send = vi.fn()
  close = vi.fn()
  open() { this.dispatchEvent(new Event('open')) }
  receive(value: unknown) { this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(value) })) }
  ready() { this.open(); this.receive({ type: 'stream.ready', event_id: 'e1' }) }
  change(version: number, extra: Record<string, unknown> = {}) {
    this.receive({ type: 'progress.updated', event_id: 'e1', scope: 'judge', version, ...extra })
  }
}
const sessions: RealtimeSync[] = []
const flush = () => vi.advanceTimersByTimeAsync(0)

function setup(overrides: Partial<SyncOptions> = {}) {
  const data = { current: 1, server: 1 }
  const sockets: Socket[] = []
  const options = {
    eventId: 'e1', role: 'judge' as const,
    ticket: vi.fn(async () => ({ ticket: 'short-lived', stream_path: '/stream' })),
    version: vi.fn(async () => data.server),
    snapshot: vi.fn(async () => { data.current = data.server; return data.current }),
    currentVersion: () => data.current,
    socket: () => { const ws = new Socket(); sockets.push(ws); return ws as unknown as WebSocket },
    status: vi.fn(), verified: vi.fn(), invalid: vi.fn(),
  }
  const sync = new RealtimeSync({ ...options, ...overrides })
  sessions.push(sync)
  return { data, sockets, options, sync }
}

beforeEach(() => { vi.useFakeTimers(); vi.spyOn(Math, 'random').mockReturnValue(0.5) })
afterEach(() => { sessions.splice(0).forEach(s => s.stop()); vi.useRealTimers(); vi.restoreAllMocks() })

describe('realtime recovery', () => {
  it('buffers during snapshot, deduplicates, merges gaps, and isolates event/scope', async () => {
    const f = setup()
    let resolve!: () => void
    const first = new Promise<void>(done => { resolve = done })
    f.options.snapshot.mockImplementationOnce(async () => { await first; f.data.current = 5; return 5 })
    f.sync.resume(false)
    await flush()
    f.sockets[0].ready()
    f.data.server = 8
    f.sockets[0].change(8)
    f.sockets[0].change(7)
    resolve()
    await flush()
    expect(f.data.current).toBe(8)
    expect(f.options.snapshot).toHaveBeenCalledTimes(2)
    f.sockets[0].change(8)
    f.sockets[0].change(9, { scope: 'admin' })
    f.sockets[0].change(9, { event_id: 'other' })
    await vi.advanceTimersByTimeAsync(100)
    expect(f.options.snapshot).toHaveBeenCalledTimes(2)
    f.data.server = 12
    f.sockets[0].change(12)
    f.sockets[0].change(10)
    await vi.advanceTimersByTimeAsync(100)
    expect(f.data.current).toBe(12)
    expect(f.options.snapshot).toHaveBeenCalledTimes(3)
    expect(f.sockets[0].send).toHaveBeenCalledWith(JSON.stringify({ ticket: 'short-lived' }))
  })

  it('recovers a lost final notification via periodic version check without reloading unchanged data', async () => {
    const f = setup()
    f.sync.resume(false); await flush(); f.sockets[0].ready(); await flush()
    f.data.server = 2
    await vi.advanceTimersByTimeAsync(30_000)
    expect(f.data.current).toBe(2)
    expect(f.options.snapshot).toHaveBeenCalledTimes(2)
    f.sockets[0].receive({ type: 'stream.heartbeat' })
    await vi.advanceTimersByTimeAsync(30_000)
    expect(f.options.version).toHaveBeenCalledTimes(2)
    expect(f.options.snapshot).toHaveBeenCalledTimes(2)
  })

  it('polls at five seconds despite repeated connection failures and stops polling once connected', async () => {
    const f = setup()
    f.options.ticket.mockRejectedValue(new ApiError(503, 'REALTIME_UNAVAILABLE', 'offline'))
    f.sync.resume(false); await flush()
    await vi.advanceTimersByTimeAsync(5000)
    expect(f.options.snapshot).toHaveBeenCalledTimes(1)
    f.options.ticket.mockResolvedValue({ ticket: 'new', stream_path: '/stream' })
    await vi.advanceTimersByTimeAsync(2000)
    f.sockets[0].ready(); await flush()
    const count = f.options.snapshot.mock.calls.length
    await vi.advanceTimersByTimeAsync(10_000)
    expect(f.options.snapshot).toHaveBeenCalledTimes(count)
  })

  it('honors Retry-After for snapshot failures and preserves the current version', async () => {
    const f = setup()
    f.options.ticket.mockRejectedValue(new ApiError(503, 'REALTIME_UNAVAILABLE', 'offline'))
    f.options.snapshot.mockRejectedValueOnce(new ApiError(503, 'SERVICE_UNAVAILABLE', 'busy', null, 60))
    f.sync.resume(false); await flush()
    await vi.advanceTimersByTimeAsync(5000)
    expect(f.options.snapshot).toHaveBeenCalledTimes(1)
    expect(f.data.current).toBe(1)
    await vi.advanceTimersByTimeAsync(59_000)
    expect(f.options.snapshot).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1000)
    expect(f.options.snapshot).toHaveBeenCalledTimes(2)
  })

  it('pauses all traffic in background and restores a fresh snapshot on foreground', async () => {
    const f = setup()
    f.sync.resume(false); await flush(); f.sockets[0].ready(); await flush()
    f.sync.pause()
    const count = f.options.snapshot.mock.calls.length
    await vi.advanceTimersByTimeAsync(120_000)
    expect(f.options.snapshot).toHaveBeenCalledTimes(count)
    expect(f.options.version).not.toHaveBeenCalled()
    f.data.server = 4
    f.sync.resume(); await flush()
    expect(f.data.current).toBe(4)
    expect(f.options.snapshot).toHaveBeenCalledTimes(count + 1)
  })

  it('expires immediately on revocation and never reconnects or submits anything', async () => {
    const f = setup()
    f.sync.resume(false); await flush(); f.sockets[0].ready(); await flush()
    f.sockets[0].receive({ type: 'session.revoked' })
    expect(f.options.invalid).toHaveBeenCalledOnce()
    expect(f.options.status).toHaveBeenLastCalledWith('expired')
    await vi.advanceTimersByTimeAsync(120_000)
    expect(f.options.ticket).toHaveBeenCalledTimes(1)
    expect(f.sockets[0].send).toHaveBeenCalledTimes(1)
  })

  it('discards a ticket arriving after identity teardown', async () => {
    let resolve!: (value: { ticket: string; stream_path: string }) => void
    const f = setup({ ticket: () => new Promise(done => { resolve = done }) })
    f.sync.resume(false)
    f.sync.stop()
    resolve({ ticket: 'old-identity', stream_path: '/stream' })
    await flush()
    expect(f.sockets).toHaveLength(0)
    expect(f.options.snapshot).not.toHaveBeenCalled()
  })

  it('uses a new ticket after heartbeat timeout and performs resync even at the same version', async () => {
    const f = setup()
    f.sync.resume(false); await flush(); f.sockets[0].ready(); await flush()
    f.sockets[0].receive({ type: 'stream.resync', event_id: 'e1' }); await flush()
    expect(f.options.snapshot).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(46_000)
    expect(f.options.ticket).toHaveBeenCalledTimes(2)
    expect(f.sockets[0].close).toHaveBeenCalled()
  })
})

