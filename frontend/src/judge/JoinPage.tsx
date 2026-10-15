import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Form, Input, Spin } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useLocation, useNavigate, useParams } from 'react-router'
import { judgeAuth } from '../api/judge'
import { ApiError } from '../api/client'
import type { ConfirmationInfo } from '../api/types'
import { takeFragmentParams } from '../lib/fragment'
import { useNow } from '../lib/useNow'
import { JudgeError, sessionKey, useForgetJudge, useJudgeSession } from './session'

export function JoinPage() {
  const { publicCode = '' } = useParams()
  return <JoinForm key={publicCode} publicCode={publicCode} />
}

function JoinForm({ publicCode }: { publicCode: string }) {
  const location = useLocation()
  const navigate = useNavigate()
  const client = useQueryClient()
  const session = useJudgeSession()
  const forget = useForgetJudge()
  const [code, setCode] = useState('')
  const [confirmation, setConfirmation] = useState<ConfirmationInfo | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const lock = useRef(false)
  const invitation = useRef<string | null>(null)
  const preview = useQuery({
    queryKey: ['join-preview', publicCode],
    queryFn: () => judgeAuth.preview(publicCode),
    enabled: !!publicCode,
  })
  const now = useNow(!!confirmation)
  const expired = !!confirmation && Date.parse(confirmation.expires_at) <= now

  const verify = useCallback(async (value: string) => {
    if (lock.current) return
    lock.current = true
    setBusy(true)
    setError(null)
    setConfirmation(null)
    try {
      const result = await judgeAuth.verify(publicCode, value)
      setCode('')
      setConfirmation(result)
    } catch (err) { setError(err) }
    finally { lock.current = false; setBusy(false) }
  }, [publicCode])

  useEffect(() => {
    invitation.current = takeFragmentParams(['code']).code ?? invitation.current
  }, [])
  useEffect(() => {
    if (location.state?.expired || location.state?.loggedOut) forget()
  }, [location.state, forget])
  useEffect(() => {
    if (!preview.data?.exchange_open || session.isPending || session.error || session.data || !invitation.current) return
    const value = invitation.current
    invitation.current = null
    void verify(value)
  }, [preview.data, session.isPending, session.error, session.data, verify])

  async function exchange() {
    if (!confirmation || expired || lock.current) return
    lock.current = true
    setBusy(true)
    setError(null)
    try {
      const result = await judgeAuth.exchange(confirmation.confirmation_token)
      client.removeQueries({ queryKey: ['judge'], predicate: q => q.queryKey[1] !== 'session' })
      client.setQueryData(sessionKey, result)
      navigate(`/judge/events/${result.judge.event_id}`, { replace: true })
    } catch (err) {
      // An exchange can succeed even when its response is lost. Restore via /me, never silently re-exchange.
      if (err instanceof ApiError && (err.status === 0 || err.status >= 500)) {
        try {
          const restored = await judgeAuth.me()
          if (restored.judge.id === confirmation.judge.id && restored.judge.event_id === confirmation.judge.event_id) {
            client.setQueryData(sessionKey, restored)
            navigate(`/judge/events/${restored.judge.event_id}`, { replace: true })
            return
          }
        } catch { /* Keep the original exchange error. */ }
      }
      setError(err)
      if (err instanceof ApiError && err.code === 'CONFIRMATION_EXPIRED') setConfirmation(null)
    } finally { lock.current = false; setBusy(false) }
  }

  async function logout() {
    if (lock.current) return
    lock.current = true
    setBusy(true)
    try { await judgeAuth.logout(); forget() }
    catch (err) { setError(err) }
    finally { lock.current = false; setBusy(false) }
  }

  return <main className="judge-stack judge-join">
    <header><p className="judge-eyebrow">评委手机评分</p><h1>加入活动</h1></header>
    {location.state?.expired && <Alert type="warning" showIcon title="身份已失效，请重新验证身份码" />}
    {error != null && <JudgeError error={error} />}
    {session.error && <><JudgeError error={session.error} /><Button onClick={() => void session.refetch()}>重新确认身份</Button></>}
    {session.data && <Card title="当前已登录" className="judge-identity-card">
      <div className="judge-identity-row"><strong>{session.data.judge.number} · {session.data.judge.name}</strong>
        <Link className="judge-link" to={`/judge/events/${session.data.judge.event_id}`}>继续评分</Link></div>
      <Button block loading={busy} onClick={() => void logout()}>退出当前身份</Button>
    </Card>}
    {!publicCode ? <Card>
      <Form layout="vertical" onFinish={(values: { publicCode: string }) => navigate(`/join/${values.publicCode.trim().toUpperCase()}`)}>
        <Form.Item name="publicCode" label="活动码" rules={[{ required: true, pattern: /^[a-zA-Z0-9]{12}$/, message: '请输入 12 位字母数字活动码', transform: value => value?.trim() }]}>
          <Input autoCapitalize="characters" autoComplete="off" maxLength={16} placeholder="请输入主办方提供的活动码" />
        </Form.Item><Button type="primary" htmlType="submit" block>查看活动</Button>
      </Form><p className="judge-muted judge-join-hint">也可扫描活动公共二维码或打开私人邀请链接加入。</p>
    </Card> : <>
      {preview.isPending && <Spin />}
      {preview.error && <><JudgeError error={preview.error} /><Button onClick={() => void preview.refetch()}>重新加载活动</Button></>}
      {preview.data && <Card>
        <h2>{preview.data.title}</h2>
        <p>{preview.data.organization}</p><p className="judge-description">{preview.data.description}</p>
        <p className="judge-muted">活动码：{preview.data.public_code}</p>
        {!preview.data.exchange_open ? <Alert type="info" title="活动已结束，停止加入" /> : !session.data && !session.isPending && !session.error && <>
          {confirmation ? <section className="judge-stack" aria-label="身份确认">
            <h3>请确认您的身份</h3><p>编号：{confirmation.judge.number}</p><p>姓名：{confirmation.judge.name}</p>
            <p className="judge-muted">确认后将在当前浏览器登录此评委身份。换机需联系主办方。</p>
            {expired && <Alert type="warning" title="身份确认已过期，请重新验证" />}
            <Button type="primary" block loading={busy} disabled={expired} onClick={() => void exchange()}>确认是我，加入活动</Button>
            <Button disabled={busy} onClick={() => setConfirmation(null)}>重新输入身份码</Button>
          </section> : <Form layout="vertical" onFinish={() => void verify(code)}>
            <Form.Item label="个人身份码" htmlFor="judge-code" required><Input.Password id="judge-code" value={code} maxLength={128} autoComplete="off" onChange={e => setCode(e.target.value)} /></Form.Item>
            <Button type="primary" htmlType="submit" block loading={busy} disabled={!code.trim()}>验证身份</Button>
            <p className="judge-muted">身份码由主办方私下提供，与评委编号不同，请勿转发。</p>
          </Form>}
        </>}
      </Card>}
      <Link className="judge-link" to="/join">使用其他活动码</Link>
    </>}
  </main>
}
