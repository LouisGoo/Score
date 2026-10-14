import dayjs from 'dayjs'
import type { EventStatus } from '../api/types'
import { fragmentUrl, publicBaseUrl } from '../lib/fragment'

export const eventStatusLabel: Record<EventStatus, { text: string; color: string }> = {
  DRAFT: { text: '草稿', color: 'default' },
  READY: { text: '已发布', color: 'blue' },
  RUNNING: { text: '进行中', color: 'green' },
  FINISHED: { text: '已结束', color: 'purple' },
  ARCHIVED: { text: '已归档', color: 'default' },
}

/** 服务端时间为 UTC，按本机时区展示到分钟。 */
export function formatTime(value: string | null | undefined): string {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '—'
}

export function formatDuration(seconds: number | null | undefined): string {
  if (!seconds) return '不限时'
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  if (!minutes) return `${rest} 秒`
  return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分钟`
}

/** 公共入口只含活动码，可用于公共二维码与大屏。 */
export function publicJoinUrl(publicCode: string): string {
  return `${publicBaseUrl().replace(/\/$/, '')}/join/${encodeURIComponent(publicCode)}`
}

/** 私人邀请：身份码放在 fragment，不随请求发送，评委页读取后立即清除。 */
export function privateInviteUrl(publicCode: string, code: string): string {
  return fragmentUrl(publicBaseUrl(), `/join/${encodeURIComponent(publicCode)}`, { code })
}
