/**
 * 生成 UUID v4 作为评分幂等键。crypto.randomUUID 仅在安全上下文（HTTPS/localhost）可用，
 * 局域网 HTTP 调试时回退到 getRandomValues。
 */
export function newIdempotencyKey(source: Crypto = crypto): string {
  if (typeof source.randomUUID === 'function') {
    try {
      return source.randomUUID()
    } catch {
      // 非安全上下文中可能抛出，使用下面的回退实现。
    }
  }
  const bytes = source.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}
