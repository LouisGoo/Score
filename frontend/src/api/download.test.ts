import { afterEach, describe, expect, it, vi } from 'vitest'
import { adminExports } from './admin'
import { ApiError, createClient, csvFilename, requestFile } from './client'
import { saveDownload } from '../lib/download'

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

describe('CSV download', () => {
  it('uses the contract, cookies, no-store and the Chinese filename, preserving bytes', async () => {
    const name = '中文比赛-成绩汇总-已公布.csv'
    const content = new TextEncoder().encode('\ufeff活动,最终分\r\n中文,90.00\r\n')
    const fetcher = vi.fn(async () => new Response(content, { headers: {
      'Content-Type': 'text/csv; charset=utf-8',
      'Content-Disposition': `attachment; filename="summary.csv"; filename*=UTF-8''${encodeURIComponent(name)}`,
    } }))
    vi.stubGlobal('fetch', fetcher)
    const file = await adminExports.download('中文/id', 'summary')
    expect(fetcher).toHaveBeenCalledWith('/api/v1/events/%E4%B8%AD%E6%96%87%2Fid/exports/summary?include_unpublished=false', expect.objectContaining({ credentials: 'same-origin', cache: 'no-store', method: 'GET' }))
    expect(file.filename).toBe(name)
    expect(Array.from(new Uint8Array(await file.blob.arrayBuffer()))).toEqual(Array.from(content))
    await adminExports.download('e1', 'audit', true)
    expect(fetcher).toHaveBeenLastCalledWith('/api/v1/events/e1/exports/audit?include_unpublished=true', expect.anything())
  })

  it.each([
    [null, 'export.csv'],
    ['attachment; filename="plain.csv"', 'plain.csv'],
    ['attachment; filename=plain.csv', 'plain.csv'],
    ["attachment; filename*=UTF-8''%ZZ; filename=backup.csv", 'backup.csv'],
    ["attachment; filename*=UTF-8''..%2Fsecret%0A.csv", '_secret_.csv'],
    ['attachment; filename="unsafe.html"', 'export.csv'],
  ])('handles missing, invalid or unsafe filenames: %s', (header, expected) => {
    expect(csvFilename(header)).toBe(expected)
  })

  it('preserves the shared JSON error, request id and retry information', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: { code: 'SERVICE_UNAVAILABLE', message: '服务暂时不可用' } }), { status: 503, headers: { 'X-Request-ID': 'request-1', 'Retry-After': '3' } })))
    await expect(requestFile('/x')).rejects.toMatchObject({ status: 503, code: 'SERVICE_UNAVAILABLE', requestId: 'request-1', retryAfter: 3 })
  })

  it('rejects an HTML success response instead of saving a bogus CSV', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>login</html>', { headers: { 'Content-Type': 'text/html' } })))
    await expect(requestFile('/x')).rejects.toMatchObject({ code: 'DOWNLOAD_INVALID' })
  })

  it('keeps authentication headers on file requests', async () => {
    const fetcher = vi.fn(async () => new Response('x', { headers: { 'Content-Type': 'text/csv' } }))
    vi.stubGlobal('fetch', fetcher)
    await createClient({ bearer: () => 'token' }).download('/x')
    expect(fetcher).toHaveBeenCalledWith('/api/v1/x', expect.objectContaining({ headers: { Authorization: 'Bearer token' } }))
  })

  it('reports stream failure and network failure as retryable downloads, with no automatic retry', async () => {
    const response = new Response('csv', { headers: { 'Content-Type': 'text/csv' } })
    vi.spyOn(response, 'blob').mockRejectedValue(new TypeError('stream interrupted'))
    const fetcher = vi.fn().mockResolvedValueOnce(response).mockRejectedValueOnce(new TypeError('network'))
    vi.stubGlobal('fetch', fetcher)
    await expect(requestFile('/x')).rejects.toMatchObject({ code: 'DOWNLOAD_FAILED' })
    await expect(requestFile('/x')).rejects.toMatchObject({ code: 'DOWNLOAD_FAILED' })
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('keeps the deadline active while reading the body and cancels explicitly', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn(async (_url, init: RequestInit) => {
      const response = new Response('csv', { headers: { 'Content-Type': 'text/csv' } })
      vi.spyOn(response, 'blob').mockImplementation(() => new Promise((_resolve, reject) => {
        init.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
      }))
      return response
    }))
    const timed = requestFile('/x', { timeoutMs: 20 }).catch(error => error)
    await vi.advanceTimersByTimeAsync(21)
    expect(await timed).toMatchObject({ code: 'DOWNLOAD_FAILED' })
    const controller = new AbortController()
    const cancelled = requestFile('/x', { signal: controller.signal }).catch(error => error)
    await vi.advanceTimersByTimeAsync(0)
    controller.abort()
    expect(await cancelled).toMatchObject({ name: 'AbortError' })
    expect(vi.getTimerCount()).toBe(0)
  })

  it('starts a browser download then releases the URL and temporary element', () => {
    vi.useFakeTimers()
    const create = vi.fn(() => 'blob:local')
    const revoke = vi.fn()
    vi.stubGlobal('URL', class extends URL { static createObjectURL = create; static revokeObjectURL = revoke })
    let name = ''
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      name = this.download
      expect(this.href).toBe('blob:local')
      expect(this.isConnected).toBe(true)
    })
    saveDownload({ blob: new Blob(['csv']), filename: '中文.csv' })
    expect(name).toBe('中文.csv')
    expect(document.querySelector('a[download]')).toBeNull()
    expect(revoke).not.toHaveBeenCalled()
    vi.advanceTimersByTime(60_000)
    expect(revoke).toHaveBeenCalledWith('blob:local')
  })

  it('cleans up failed saves', () => {
    const revoke = vi.fn()
    vi.stubGlobal('URL', class extends URL { static createObjectURL = () => 'blob:local'; static revokeObjectURL = revoke })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => { throw new Error('blocked') })
    expect(() => saveDownload({ blob: new Blob(['csv']), filename: '中文.csv' })).toThrow(ApiError)
    expect(revoke).toHaveBeenCalledWith('blob:local')
    expect(document.querySelector('a[download]')).toBeNull()
  })
})
