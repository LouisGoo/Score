import dayjs from 'dayjs'
import type { EventStatus, RoundStatus } from '../api/types'
import { fragmentUrl, publicBaseUrl } from '../lib/fragment'

export const eventStatusLabel: Record<EventStatus, { text: string; color: string }> = {
  DRAFT: { text: '草稿', color: 'default' },
  READY: { text: '已发布', color: 'blue' },
  RUNNING: { text: '进行中', color: 'green' },
  FINISHED: { text: '已结束', color: 'purple' },
  ARCHIVED: { text: '已归档', color: 'default' },
}

export const roundStatusLabel: Record<RoundStatus, { text: string; color: string }> = {
  PENDING: { text: '待评分', color: 'default' },
  OPEN: { text: '评分中', color: 'green' },
  PAUSED: { text: '已暂停', color: 'orange' },
  CLOSED: { text: '已收评', color: 'gold' },
  PUBLISHED: { text: '已公布', color: 'blue' },
  SKIPPED: { text: '已跳过', color: 'default' },
  NO_RESULT: { text: '无结果', color: 'red' },
}

export const algorithmLabel: Record<'mean' | 'trimmed_mean', string> = {
  mean: '平均分',
  trimmed_mean: '去最高最低后平均',
}

/** 精确到秒，用于收评、回执等需要核对先后的时间。 */
export function formatSeconds(value: string | null | undefined): string {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '—'
}

export function formatClock(value: string | number | null | undefined): string {
  return value ? dayjs(value).format('HH:mm:ss') : '—'
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
