import { useEffect, useState } from 'react'
import type { ScreenSnapshot } from '../api/types'
import { formatCountdown, pausedRemainingMs, remainingMs } from '../lib/clock'
import { formatScore } from '../lib/decimal'
import type { DisplaySnapshot } from './data'

/** A long published leaderboard rotates in readable pages instead of shrinking every row. */
function Leaderboard({ snapshot, ended }: { snapshot: ScreenSnapshot; ended: boolean }) {
  const [pageSize, setPageSize] = useState(() => window.innerHeight >= 1000 ? 8 : 5)
  useEffect(() => {
    const resize = () => setPageSize(window.innerHeight >= 1000 ? 8 : 5)
    window.addEventListener('resize', resize)
    return () => window.removeEventListener('resize', resize)
  }, [])
  const published = new Set(snapshot.published_results.map(r => r.entry_id))
  const rows = snapshot.ranking.filter(r => published.has(r.entry_id)).slice(0, snapshot.display.leaderboard_limit)
  const pages = Math.max(1, Math.ceil(rows.length / pageSize))
  const [page, setPage] = useState(0)
  useEffect(() => {
    if (pages < 2) return
    const timer = setInterval(() => { if (!document.hidden) setPage(p => (p + 1) % pages) }, 10000)
    return () => clearInterval(timer)
  }, [pages])
  const current = page % pages
  return <section className="screen-leaderboard">
    <p className="screen-eyebrow">{ended ? '感谢每一位参与者' : '已公布成绩'}</p>
    <h2>{ended ? '活动已结束' : '排行榜'}</h2>
    {rows.length ? <table><thead><tr><th>名次</th><th>评分对象</th><th>最终成绩</th></tr></thead>
      <tbody>{rows.slice(current * pageSize, (current + 1) * pageSize).map(row => <tr key={row.entry_id}>
        <td className="screen-rank">{row.rank}</td><td><span className="screen-entry-number">{row.number}</span>{row.name}</td><td className="screen-ranking-score">{formatScore(row.final_score)}</td>
      </tr>)}</tbody></table> : <p className="screen-hint">暂无已公布成绩</p>}
    <p className="screen-ranking-note">仅展示已公布对象 · 共 {rows.length} 项{pages > 1 && ` · 第 ${current + 1} / ${pages} 页，每 10 秒切换`}</p>
  </section>
}

export function ScreenContent({ snapshot, now }: { snapshot: DisplaySnapshot; now: number }) {
  const { display, current_round: round } = snapshot
  if (display.mode === 'leaderboard' || display.mode === 'ended') return <Leaderboard key={display.mode} snapshot={snapshot} ended={display.mode === 'ended'} />
  if (display.mode === 'waiting') return <section className="screen-main screen-waiting">
    <p className="screen-eyebrow">欢迎来到现场</p><h2>等待主持人开评</h2><p className="screen-hint">{snapshot.event.description || '请评委加入活动，确认身份后等待评分开始。'}</p>
    <div className="screen-waiting-line" aria-hidden="true" /><p className="screen-hint">公平评价 · 独立评分</p>
  </section>
  if (!round || round.id !== display.round_id) return <section className="screen-main"><h2>等待同步展示对象</h2></section>
  if (display.mode === 'result') {
    const result = snapshot.published_results.find(r => r.round_id === display.round_id)
    if (!result || round.status !== 'PUBLISHED') return <section className="screen-main"><h2>成绩尚未公布</h2></section>
    return <section className="screen-main screen-result"><p className="screen-eyebrow">成绩已公布 · {result.number}</p><h2>{result.name}</h2>
      <div className="screen-final-score">{formatScore(result.final_score)}<span>分</span></div>
      <div className="screen-result-meta"><span>有效评分 {result.valid_count} / {result.expected_count}</span><span>{result.algorithm === 'trimmed_mean' ? '去最高最低后平均' : '平均分'}</span></div>
      <p className="screen-hint">公布于 {new Date(result.published_at).toLocaleString('zh-CN', { hour12: false })}</p>
    </section>
  }
  const paused = display.mode === 'paused'
  if (round.status !== (paused ? 'PAUSED' : 'OPEN')) return <section className="screen-main"><h2>对象状态已变化，等待同步</h2></section>
  const remaining = paused ? pausedRemainingMs(round.remaining_seconds) : remainingMs(round.deadline_at, snapshot.offsetMs, now)
  const percent = round.expected_count ? Math.max(0, Math.min(100, round.submitted_count / round.expected_count * 100)) : 0
  return <section className={`screen-main screen-progress ${paused ? 'screen-paused' : ''}`}>
    <p className="screen-eyebrow">{paused ? '评分已暂停' : '正在评分'} · {round.number}</p><h2>{round.name}</h2>
    <p className="screen-hint screen-round-description">{round.description}</p>
    <div className="screen-progress-stats"><div><p>已交 / 应交</p><strong>{round.submitted_count}<span> / {round.expected_count}</span></strong></div>
      <div><p>{paused ? '剩余时间已冻结' : '剩余时间'}</p><strong className={remaining === 0 ? 'time-expired' : ''}>{formatCountdown(remaining)}</strong></div></div>
    <div className="screen-progress-track" role="progressbar" aria-label="评分提交进度" aria-valuemin={0} aria-valuemax={round.expected_count} aria-valuenow={round.submitted_count}><div style={{ width: `${percent}%` }} /></div>
    <p className="screen-hint">{paused ? '请稍候，主持人恢复后可继续提交。' : remaining === 0 ? '评分时间已到，等待主持人处理。' : '请评委在手机上独立完成评分，成绩将在公布后显示。'}</p>
  </section>
}
