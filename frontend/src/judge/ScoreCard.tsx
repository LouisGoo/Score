import { useEffect, useEffectEvent, useRef, useState } from 'react'
import { Big } from 'big.js'
import { Alert, Button, Card, Input, Modal } from 'antd'
import { ApiError } from '../api/client'
import { judgeScoring } from '../api/judge'
import type { BallotReceipt, PublicRound } from '../api/types'
import { formatCountdown, pausedRemainingMs, remainingMs } from '../lib/clock'
import { clearDraft, loadDraft, saveDraft, type DraftScores } from '../lib/drafts'
import { DECIMAL_PATTERN, personalTotal, scoreError } from '../lib/decimal'
import { newIdempotencyKey } from '../lib/ids'
import { useNow } from '../lib/useNow'
import { receiptsFor, type MobileSnapshot } from './data'
import { JudgeError } from './session'
import { Receipt, ScoreSummary } from './Receipt'
import { clearSubmission, pendingSubmissions, saveSubmission, type PendingSubmission } from './storage'

interface Props {
  snapshot: MobileSnapshot
  round: PublicRound
  synced: boolean
  refresh: () => Promise<MobileSnapshot | undefined>
  onExpired: () => void
}

/** Keyed by event, identity, round and rule: local inputs can never migrate to a different object. */
export function ScoreCard({ snapshot, round, synced, refresh, onExpired }: Props) {
  const scope = { eventId: snapshot.event.id, judgeId: snapshot.identity.id, roundId: round.id, ruleVersion: snapshot.rule_version }
  const [scores, setScores] = useState<DraftScores>(() => loadDraft(scope) ?? {})
  const [pending, setPending] = useState<PendingSubmission | null>(() => pendingSubmissions(scope.eventId, scope.judgeId)
    .find(item => item.scope.roundId === round.id && item.scope.ruleVersion === scope.ruleVersion) ?? null)
  const [accepted, setAccepted] = useState<BallotReceipt | null>(null)
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const lock = useRef(false)
  const [error, setError] = useState<unknown>(null)
  const [note, setNote] = useState('')
  const [validated, setValidated] = useState(false)
  const [confirmation, setConfirmation] = useState<{ revision: number; roundVersion: number } | null>(null)
  const [retryAt, setRetryAt] = useState(0)
  const now = useNow(round.status === 'OPEN' || retryAt > 0)
  const serverReceipt = receiptsFor(snapshot, round.id)[0]
  const receipt = accepted && (!serverReceipt || accepted.revision > serverReceipt.revision) ? accepted : serverReceipt
  const remaining = round.status === 'PAUSED' ? pausedRemainingMs(round.remaining_seconds) : remainingMs(round.deadline_at, snapshot.offsetMs, now)
  const canSubmit = synced && navigator.onLine && snapshot.event.status === 'RUNNING' && round.status === 'OPEN'
    && remaining !== 0 && (!receipt || snapshot.allow_revisions)
  const total = personalTotal(snapshot.rule.criteria, scores)
  const confirmationValid = !!confirmation && confirmation.revision === (receipt?.revision ?? 0) && confirmation.roundVersion === round.version
  const waiting = busy || now < retryAt

  function handleError(err: unknown) {
    if (err instanceof ApiError && err.status === 401) { onExpired(); return }
    setError(err)
    if (err instanceof ApiError && err.retryAfter) setRetryAt(Date.now() + err.retryAfter * 1000)
  }

  function complete(result: BallotReceipt, item: PendingSubmission) {
    setAccepted(result)
    clearSubmission(scope, item.key)
    try { clearDraft(scope) } catch { /* The receipt is already durable on the server. */ }
    setPending(null)
    setEditing(false)
    setScores({})
    setNote('')
    setError(null)
    void refresh()
  }

  async function verify(item: PendingSubmission) {
    if (lock.current || Date.now() < retryAt) return
    lock.current = true
    setBusy(true)
    setError(null)
    try { complete(await judgeScoring.receipt(item.scope.roundId, item.key), item) }
    catch (err) {
      handleError(err)
      setNote('尚未确认本次提交。请联网后再次核验，或使用原提交重试；不会自动补交。')
    } finally { lock.current = false; setBusy(false) }
  }

  // A remount/refresh recovers only the exact receipt; it never sends a score automatically.
  const checked = useRef(false)
  const recover = useEffectEvent((item: PendingSubmission) => { void verify(item) })
  useEffect(() => {
    if (!checked.current && pending) { checked.current = true; recover(pending) }
  }, [pending])

  async function send(item: PendingSubmission, retry: boolean) {
    if (lock.current || Date.now() < retryAt) return
    lock.current = true
    setBusy(true)
    setError(null)
    setConfirmation(null)
    let mustVerify = false
    try {
      if (retry) {
        // A reconnect must synchronize state first. The original key/body are still used, even after closure.
        const fresh = await refresh()
        if (!fresh) { setNote('无法同步活动，请恢复连接后重试。'); return }
      }
      complete(await judgeScoring.submit(item.scope.roundId, item.body, item.key), item)
    } catch (err) {
      handleError(err)
      // Network/5xx can hide a committed transaction. A keyed retry checks for its receipt before business validation.
      const unknown = !(err instanceof ApiError) || err.status === 0 || err.status >= 500
      if (unknown || (err instanceof ApiError && err.code === 'IDEMPOTENCY_CONFLICT')) {
        setNote('正在核验提交结果，请勿重复创建提交。')
        mustVerify = !(err instanceof ApiError && err.retryAfter)
      } else {
        clearSubmission(scope, item.key)
        setPending(null)
        setNote('提交未被接受，草稿已保留。请同步最新状态后重新确认。')
        await refresh()
      }
    } finally {
      lock.current = false
      setBusy(false)
    }
    if (mustVerify) await verify(item)
  }

  async function preview() {
    if (lock.current || pending) return
    setValidated(true)
    if (total === null) return
    lock.current = true
    setBusy(true)
    setError(null)
    try {
      const fresh = await refresh()
      if (!fresh) { setNote('无法同步活动，请联网后再确认提交。'); return }
      const nextRound = fresh.rounds.find(r => r.id === round.id)
      const nextReceipt = receiptsFor(fresh, round.id)[0]
      if (fresh.rule_version !== scope.ruleVersion || nextRound?.version !== round.version
        || (nextReceipt?.revision ?? 0) !== (receipt?.revision ?? 0)) {
        setNote('对象状态或评分版本已变化，请查看最新状态后重新确认。')
        return
      }
      if (fresh.event.status !== 'RUNNING' || nextRound.status !== 'OPEN'
        || remainingMs(nextRound.deadline_at, fresh.offsetMs) === 0 || (nextReceipt && !fresh.allow_revisions)) {
        setNote('当前对象暂不可提交，草稿已保留。')
        return
      }
      setConfirmation({ revision: nextReceipt?.revision ?? 0, roundVersion: nextRound.version })
    } finally { lock.current = false; setBusy(false) }
  }

  function confirm() {
    if (!canSubmit || !confirmationValid || total === null || pending || lock.current) return
    const item: PendingSubmission = {
      scope, key: newIdempotencyKey(),
      body: {
        rule_version: scope.ruleVersion,
        expected_ballot_revision: confirmation!.revision,
        scores: snapshot.rule.criteria.map(c => ({ criterion_id: c.criterion_id, value: scores[c.criterion_id].trim() })),
      },
    }
    if (!saveSubmission(item)) {
      setConfirmation(null)
      const existing = pendingSubmissions(scope.eventId, scope.judgeId).find(p => p.scope.roundId === scope.roundId && p.scope.ruleVersion === scope.ruleVersion)
      if (existing) {
        setPending(existing)
        setNote('其他页面已有待核验提交，请先核验原提交结果。')
        return
      }
      setNote('浏览器无法保存提交记录。请允许本地存储或释放空间后重试，以便断网后核验回执。')
      return
    }
    setPending(item)
    // Mark before setting pending so the recovery effect does not race the first PUT.
    checked.current = true
    void send(item, false)
  }

  function change(id: string, value: string) {
    const next = { ...scores, [id]: value }
    setScores(next)
    saveDraft(scope, next)
  }

  const statusText = { PENDING: '等待开评', OPEN: '评分中', PAUSED: '评分已暂停', CLOSED: '已收评', PUBLISHED: '成绩已公布', SKIPPED: '已跳过', NO_RESULT: '无结果' }[round.status]
  return <Card className="judge-round">
    <div className="judge-round-heading"><span>{statusText}</span><span className="judge-countdown">{formatCountdown(remaining)}</span></div>
    <h2>{round.number} · {round.name}</h2><p className="judge-description">{round.description}</p>
    <p className="judge-muted">已交 {round.submitted_count} / {round.expected_count} · 截止以服务端接收时间为准</p>
    {round.status === 'PAUSED' && <Alert type="warning" title="主持人已暂停评分，草稿保留，恢复后可继续提交" />}
    {round.status === 'OPEN' && remaining === 0 && <Alert type="warning" title="评分时间已到，等待主持人处理" />}
    {note && <Alert className="judge-notice" type="info" title={note} />}
    {error != null && <JudgeError error={error} />}
    {receipt && <Receipt receipt={receipt} rule={snapshot.rule} />}
    {pending ? <section className="judge-stack judge-notice" aria-label="待核验提交">
      <Alert type="warning" showIcon title="正在核验提交结果" description="未收到本次服务端回执前，不能确认评分已保存。刷新页面后仍可继续核验。" />
      <ScoreSummary scores={pending.body.scores} rule={snapshot.rule} />
      <div className="judge-actions"><Button disabled={waiting || !navigator.onLine} onClick={() => void verify(pending)}>核验提交结果</Button>
        <Button disabled={waiting || !navigator.onLine} onClick={() => void send(pending, true)}>使用原提交重试</Button></div>
    </section> : <>
      {receipt && !editing && canSubmit && <Button block onClick={() => {
        const next = loadDraft(scope) ?? Object.fromEntries(receipt.scores.map(s => [s.criterion_id, s.value]))
        setScores(next); setEditing(true); setValidated(false)
      }}>修改评分</Button>}
      {receipt && !snapshot.allow_revisions && <p className="judge-muted">本活动不允许改分。</p>}
      {(!receipt || editing) && <form onSubmit={e => { e.preventDefault(); void preview() }}>
        {snapshot.rule.criteria.map(c => {
          const value = scores[c.criterion_id] ?? ''
          const validation = validated || value !== '' ? scoreError(value, c) : null
          const inputId = `score-${round.id}-${c.criterion_id}`
          function step(direction: number) {
            if (value && !DECIMAL_PATTERN.test(value.trim())) return
            const next = new Big(value.trim() || '0').plus(new Big(c.step).times(direction))
            if (next.gte(0) && next.lte(c.maximum)) change(c.criterion_id, next.toFixed())
          }
          return <div className="judge-field" key={c.criterion_id}>
            <label htmlFor={inputId}>{c.name}</label>
            <p className="judge-muted" id={`${inputId}-help`}>满分 {c.maximum} · 权重 {new Big(c.weight).times(100).toFixed()}% · 步长 {c.step}</p>
            <div className="judge-score-input">
              <Button aria-label={`减少${c.name}`} disabled={busy || !canSubmit} onClick={() => step(-1)}>−</Button>
              <Input id={inputId} inputMode="decimal" autoComplete="off" value={value} maxLength={16} placeholder="未填写"
                disabled={busy || !canSubmit} aria-invalid={!!validation} aria-describedby={`${inputId}-help ${inputId}-error`}
                status={validation ? 'error' : undefined} onChange={e => change(c.criterion_id, e.target.value)} />
              <Button aria-label={`增加${c.name}`} disabled={busy || !canSubmit} onClick={() => step(1)}>+</Button>
            </div>
            <div id={`${inputId}-error`} className="judge-field-error">{validation}</div>
          </div>
        })}
        <div className="judge-submit-bar">
          <div className="judge-total">个人总分预览 <strong>{total ?? '待填写'}</strong></div>
          <p className="judge-muted">仅供预览，保存结果以服务端回执为准。</p>
          <Button type="primary" htmlType="submit" block loading={busy} disabled={!canSubmit || waiting}>核对并提交</Button>
          {editing && <Button block disabled={busy} onClick={() => { setEditing(false); setConfirmation(null) }}>返回已保存评分</Button>}
        </div>
      </form>}
    </>}
    <Modal title="确认本次评分" open={!!confirmation} onCancel={() => setConfirmation(null)} onOk={confirm}
      okText="确认提交" cancelText="返回修改" width={480} className="judge-confirm"
      okButtonProps={{ disabled: !canSubmit || !confirmationValid || waiting }}>
      <h3>{round.number} · {round.name}</h3>
      <ScoreSummary scores={snapshot.rule.criteria.map(c => ({ criterion_id: c.criterion_id, value: scores[c.criterion_id] ?? '' }))} rule={snapshot.rule} />
      <p>个人总分预览：<strong>{total}</strong></p>
      <p>本次提交后形成评分版本 {(confirmation?.revision ?? 0) + 1}。</p>
      {(!canSubmit || !confirmationValid) && <Alert type="warning" title="状态已变化，请返回评分页重新核对" />}
    </Modal>
  </Card>
}
