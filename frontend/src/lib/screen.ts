import type { ScreenDisplay } from '../api/types'
import { publicBaseUrl } from './fragment'

export const screenModeLabels: Record<ScreenDisplay['mode'], string> = {
  waiting: '等待', progress: '评分中', paused: '暂停', result: '成绩', leaderboard: '排行榜', ended: '结束',
}

export function screenGrantUrl(grantId: string, token: string): string {
  return `${publicBaseUrl().replace(/\/$/, '')}/screen/${encodeURIComponent(grantId)}#token=${encodeURIComponent(token)}`
}

export function publicEntryUrl(publicCode: string): string {
  return `${publicBaseUrl().replace(/\/$/, '')}/join/${encodeURIComponent(publicCode)}`
}
