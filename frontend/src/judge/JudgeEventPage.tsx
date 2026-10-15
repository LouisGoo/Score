import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Modal, Spin } from 'antd'
import { Link, useNavigate, useParams } from 'react-router'
import { judgeAuth } from '../api/judge'
import { ApiError } from '../api/client'
import type { JudgeSessionInfo } from '../api/types'
import { formatScore } from '../lib/decimal'
import { receiptsFor, useJudgeSnapshot, useOnline } from './data'
import { ExpiredSession, JudgeError, JudgeGuard } from './session'
import { pendingSubmissions } from './storage'
import { ScoreCard } from './ScoreCard'
import { Receipt } from './Receipt'
import { SyncButton } from './SyncButton'

function JudgeWorkspace({ session, history }: { session: JudgeSessionInfo; history: boolean }) {
  const query = useJudgeSnapshot(session.judge.event_id, session.judge.id)
  const online = useOnline()
  const navigate = useNavigate()
  const [expired, setExpired] = useState(false)
  const [logoutOpen, setLogoutOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [logoutError, setLogoutError] = useState<unknown>(null)
  const [switched, setSwitched] = useState(false)
  const previousRound = useRef<string | null | undefined>(undefined)
  const snapshot = query.data
  const active = snapshot?.rounds.find(r => r.status === 'OPEN' || r.status === 'PAUSED')
  useEffect(() => {
    if (!snapshot) return
    const id = active?.id ?? null
    if (previousRound.current !== undefined && previousRound.current !== id) setSwitched(true)
    previousRound.current = id
  }, [active?.id, snapshot])

  if (expired || (query.error instanceof ApiError && query.error.status === 401)) return <ExpiredSession publicCode={query.publicCode ?? undefined} />
  if (!snapshot) return query.isPending ? <Spin className="page-spin" /> : <>
    <JudgeError error={query.error} /><Button onClick={() => void query.refetch()}>重新同步活动</Button>
  </>

  async function refresh() {
    const result = await query.refetch()
    return result.isError ? undefined : result.data
  }
  async function logout() {
    if (busy) return
    setBusy(true)
    setLogoutError(null)
    try {
      await judgeAuth.logout()
      navigate(`/join/${snapshot!.event.public_code}`, { replace: true, state: { loggedOut: true } })
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setExpired(true)
      else setLogoutError(err)
    } finally { setBusy(false) }
  }

  const pending = pendingSubmissions(snapshot.event.id, snapshot.identity.id)
  const extraPending = snapshot.rounds.filter(r => r.id !== active?.id && pending.some(p => p.scope.roundId === r.id))
  const ended = snapshot.event.status === 'FINISHED' || snapshot.event.status === 'ARCHIVED'
  const confirmedRounds = snapshot.rounds.filter(r => receiptsFor(snapshot, r.id).length > 0)
  const lastRound = confirmedRounds.reduce<typeof confirmedRounds[number] | undefined>((latest, round) =>
    !latest || Date.parse(receiptsFor(snapshot, round.id)[0].accepted_at) > Date.parse(receiptsFor(snapshot, latest.id)[0].accepted_at) ? round : latest, undefined)

  return <main className="judge-stack">
    <header className="judge-stack">
      <p className="judge-eyebrow">{snapshot.event.organization || '评委手机评分'}</p><h1>{snapshot.event.title}</h1>
      <div className="judge-actions"><strong>{snapshot.identity.number} · {snapshot.identity.name}</strong><Button onClick={() => setLogoutOpen(true)}>退出身份</Button></div>
      <nav className="judge-actions" aria-label="评委导航">
        <Link className={`judge-link ${!history ? 'active' : ''}`} aria-current={!history ? 'page' : undefined} to={`/judge/events/${snapshot.event.id}`}>当前评分</Link>
        <Link className={`judge-link ${history ? 'active' : ''}`} aria-current={history ? 'page' : undefined} to={`/judge/events/${snapshot.event.id}/history`}>本人记录</Link>
        <SyncButton fetching={query.isFetching} onSync={() => void refresh()} />
      </nav>
      <p className="judge-muted">{query.syncStatus === 'live' ? '实时同步' : '自动同步'} · 最后同步：{new Date(snapshot.server_time).toLocaleTimeString('zh-CN', { hour12: false })}</p>
    </header>
    {(!online || query.isError || query.syncStatus === 'recovering') && <Alert type="warning" showIcon title="连接中，数据可能延迟" description="本机草稿已保留。恢复连接后先同步状态，再由您确认提交。" />}
    {query.error && <JudgeError error={query.error} />}
    {switched && !history && <Alert type="info" title="评分对象已切换，旧对象草稿已保留，不会带入新对象" closable onClose={() => setSwitched(false)} />}
    {ended && <Alert type="info" title="活动已结束，可查看本人评分记录和已公布成绩" />}
    {extraPending.map(round => <ScoreCard key={`${round.id}:${snapshot.rule_version}`} snapshot={snapshot} round={round}
      synced={false} refresh={refresh} onExpired={() => setExpired(true)} />)}
    {history ? <>
      <h2>本人评分记录</h2>
      {!confirmedRounds.length && <Card>暂无服务端确认的评分记录。</Card>}
      {confirmedRounds.map(round => {
        const receipts = receiptsFor(snapshot, round.id)
        return <Card key={round.id}><h3>{round.number} · {round.name}</h3>
          <Receipt receipt={receipts[0]} rule={snapshot.rule} />
          {receipts.length > 1 && <details><summary>查看此前 {receipts.length - 1} 个版本</summary>
            {receipts.slice(1).map(receipt => <Receipt key={receipt.receipt_id} receipt={receipt} rule={snapshot.rule} />)}
          </details>}
        </Card>
      })}
      <h2>已公布成绩</h2>
      {!snapshot.published_results.length && <p>暂无已公布成绩。</p>}
      {snapshot.published_results.map(result => <Card key={result.round_id}>
        <h3>{result.number} · {result.name}</h3><p>最终成绩：<strong>{formatScore(result.final_score)}</strong></p>
        <p className="judge-muted">有效评分 {result.valid_count} / {result.expected_count} 份</p>
      </Card>)}
    </> : active ? <ScoreCard key={`${active.id}:${snapshot.rule_version}`} snapshot={snapshot} round={active}
      synced={online && !query.isError && !session.read_only} refresh={refresh} onExpired={() => setExpired(true)} /> : <>
      {!ended && <Card><h2>等待主持人开评</h2><p>当前没有开放的评分对象，开始后此页会自动更新。</p></Card>}
      {lastRound && !extraPending.some(r => r.id === lastRound.id) && <Card><h2>{lastRound.number} · {lastRound.name}</h2>
        <Receipt receipt={receiptsFor(snapshot, lastRound.id)[0]} rule={snapshot.rule} />
      </Card>}
    </>}
    <Modal title="退出评委身份" open={logoutOpen} onCancel={() => setLogoutOpen(false)} onOk={() => void logout()} okText="确认退出" cancelText="继续评分" confirmLoading={busy} className="judge-confirm">
      <p>退出会清理本机的草稿和待核验记录，已保存的服务端评分会保留。</p>
      {pending.length > 0 && <Alert type="warning" title={`还有 ${pending.length} 次提交待核验，建议先核验回执再退出。`} />}
      {logoutError != null && <JudgeError error={logoutError} />}
    </Modal>
  </main>
}

function Page({ history }: { history: boolean }) {
  const { eventId = '' } = useParams()
  return <JudgeGuard eventId={eventId}>{session => <JudgeWorkspace key={`${session.judge.id}:${eventId}`} session={session} history={history} />}</JudgeGuard>
}
export const JudgeEventPage = () => <Page history={false} />
export const JudgeHistoryPage = () => <Page history />
