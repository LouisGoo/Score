import type { AdminSnapshot, BallotReceipt, JudgeInfo, PublicRound, PublishedRule, ResultInfo, RoundStatus } from '../../api/types'
import { algorithmLabel } from '../format'

const TERMINAL: ReadonlySet<RoundStatus> = new Set(['PUBLISHED', 'SKIPPED', 'NO_RESULT'])

export const isTerminal = (status: RoundStatus) => TERMINAL.has(status)
export const isActive = (status: RoundStatus) => status === 'OPEN' || status === 'PAUSED'

export const roundName = (round: Pick<PublicRound, 'number' | 'name'>) => `${round.number} ${round.name}`

/** 同场最多一个评分中或暂停的任务（服务端约束）。 */
export function activeRound(rounds: PublicRound[]): PublicRound | undefined {
  return rounds.find(r => isActive(r.status))
}

/** 未指定时默认选中：评分中/暂停 → 已收评待处理 → 第一个待评分 → 第一个对象。 */
export function defaultRoundId(rounds: PublicRound[]): string | null {
  const pick =
    activeRound(rounds) ?? rounds.find(r => r.status === 'CLOSED') ?? rounds.find(r => r.status === 'PENDING') ?? rounds[0]
  return pick?.id ?? null
}

/** 当前对象之后的第一个待评分对象，没有则回到列表开头查找。 */
export function nextPendingRound(rounds: PublicRound[], currentId: string): PublicRound | undefined {
  const index = rounds.findIndex(r => r.id === currentId)
  const ordered = [...rounds.slice(index + 1), ...rounds.slice(0, Math.max(index, 0))]
  return ordered.find(r => r.status === 'PENDING')
}

export function unfinishedRounds(rounds: PublicRound[]): PublicRound[] {
  return rounds.filter(r => !isTerminal(r.status))
}

/** 结束活动前每种未完成状态的处理方式。 */
export function unfinishedHint(status: RoundStatus): string {
  switch (status) {
    case 'PENDING':
      return '开评后收评，或跳过'
    case 'OPEN':
    case 'PAUSED':
      return '先收评'
    case 'CLOSED':
      return '公布成绩、标记无结果或重开补评'
    default:
      return ''
  }
}

/** UNFINISHED_ROUNDS 的消息形如“待处理任务：id1,id2”；取出任务 ID 以映射为对象编号和名称。 */
export function parseUnfinishedIds(message: string): string[] {
  const at = message.search(/[：:]/)
  if (at < 0) return []
  return message
    .slice(at + 1)
    .split(/[,，]/)
    .map(s => s.trim())
    .filter(Boolean)
}

/** 收评快照按任务版本升序；最新一份即当前结果。 */
export function resultsFor(results: ResultInfo[], roundId: string): ResultInfo[] {
  return results.filter(r => r.round_id === roundId)
}

export function latestResult(results: ResultInfo[], roundId: string): ResultInfo | undefined {
  return resultsFor(results, roundId).at(-1)
}

export function receiptsFor(snapshot: Pick<AdminSnapshot, 'ballots'>, roundId: string, judgeId?: string): BallotReceipt[] {
  return snapshot.ballots
    .filter(b => judgeId === undefined || b.judge_id === judgeId)
    .flatMap(b => b.receipts.filter(r => r.round_id === roundId))
}

export interface JudgeStatus {
  judge: JudgeInfo
  /** 当前有效版本；0 表示未交。改分不增加已交人数。 */
  revision: number
  acceptedAt: string | null
}

/** 发布时每个任务冻结全部评委为应交名单；已交状态来自评分历史，不含分数。 */
export function judgeStatuses(snapshot: Pick<AdminSnapshot, 'judges' | 'ballots'>, roundId: string): JudgeStatus[] {
  return snapshot.judges.map(judge => {
    const latest = receiptsFor(snapshot, roundId, judge.id).reduce<BallotReceipt | null>(
      (best, r) => (best === null || r.revision > best.revision ? r : best),
      null,
    )
    return { judge, revision: latest?.revision ?? 0, acceptedAt: latest?.accepted_at ?? null }
  })
}

export function ruleSummary(rule: PublishedRule): string {
  const criteria =
    rule.mode === 'multi'
      ? `多维度 ${rule.criteria.length} 项`
      : `单项（满分 ${rule.criteria[0]?.maximum ?? '—'}，步长 ${rule.criteria[0]?.step ?? '—'}）`
  return `${criteria} · ${algorithmLabel[rule.algorithm ?? 'mean']} · K=${rule.minimum_ballots}`
}
