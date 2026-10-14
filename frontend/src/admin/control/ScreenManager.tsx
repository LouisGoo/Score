import { useRef, useState } from 'react'
import { Alert, Button, Card, Drawer, Form, Input, InputNumber, Modal, Select, Space, Switch, Tag, Typography } from 'antd'
import { adminScreens } from '../../api/admin'
import { ApiError } from '../../api/client'
import { describeError } from '../../api/errors'
import type { CreatedGrant, ScreenSettings } from '../../api/types'
import { screenGrantUrl, screenModeLabels } from '../../lib/screen'
import { useNow } from '../../lib/useNow'
import { formatTime } from '../format'
import { ErrorText, useReportError } from '../session'
import { useRefreshConsole, type ConsoleSnapshot } from './data'

export function ScreenManager({ snapshot, onClose }: { snapshot: ConsoleSnapshot; onClose: () => void }) {
  const eventId = snapshot.event.id
  const refresh = useRefreshConsole(eventId)
  const report = useReportError()
  const [issued, setIssued] = useState<CreatedGrant | null>(null)
  const [edit, setEdit] = useState<ScreenSettings | null>(null)
  const [revokeId, setRevokeId] = useState<string | null>(null)
  const [ttl, setTtl] = useState(86400)
  const [busy, setBusy] = useState(false)
  const lock = useRef(false)
  const [error, setError] = useState<unknown>(null)
  const now = useNow(true, 1000) + snapshot.offsetMs
  const activeCount = snapshot.screen_grants.filter(g => !g.revoked_at && Date.parse(g.expires_at) > now).length

  async function perform(run: () => Promise<void>, creation = false) {
    if (lock.current) return
    lock.current = true; setBusy(true); setError(null)
    try { await run(); await refresh() }
    catch (err) {
      setError(err)
      report(err)
      if (err instanceof ApiError && ['VERSION_CONFLICT', 'DISPLAY_STATE_CONFLICT'].includes(err.code)) setEdit(null)
      await refresh()
      if (creation) setIssued(null)
    } finally { lock.current = false; setBusy(false) }
  }

  const info = error ? describeError(error) : null
  const link = issued ? screenGrantUrl(issued.id, issued.token) : ''
  return <Drawer open title="大屏管理" size={680} onClose={() => { if (!busy) onClose() }} mask={{ closable: !busy }} keyboard={!busy}>
    <Space orientation="vertical" size="large" className="full-width">
      {info && <Alert type="warning" showIcon title={info.action === 'verify' || (error instanceof ApiError && error.status >= 500) ? '操作结果待核对，请勿连续重试' : '操作未完成'}
        description={<><ErrorText info={info} /><p>已重新读取活动状态。创建链接若已生效但响应丢失，无法找回令牌；请核对授权列表，撤销多余授权后再创建。</p></>} />}
      <Card size="small" title="展示设置">
        <p>当前模式：<strong>{screenModeLabels[snapshot.display.mode]}</strong> · {snapshot.display.theme === 'dark' ? '深色' : '浅色'}主题</p>
        <p>标题：{snapshot.display.title}</p>
        <p>公共二维码：{snapshot.display.show_public_qr ? '显示' : '隐藏'} · 排行榜前 {snapshot.display.leaderboard_limit} 名</p>
        <Button disabled={busy} onClick={() => setEdit({ ...snapshot.display, expected_version: snapshot.event.version })}>编辑展示设置</Button>
        <Typography.Paragraph type="secondary">开评、暂停、公布、结束会自动切换展示。活动结束后仍可切回已公布的单对象成绩。</Typography.Paragraph>
      </Card>
      <Card size="small" title="创建只读大屏链接">
        <Space wrap>
          <label htmlFor="screen-ttl">有效期</label>
          <Select id="screen-ttl" value={ttl} disabled={busy} onChange={setTtl} options={[
            { value: 3600, label: '1 小时' }, { value: 28800, label: '8 小时' }, { value: 86400, label: '24 小时' }, { value: 604800, label: '7 天' },
          ]} />
          <Button type="primary" disabled={busy || !!issued || activeCount >= 20} loading={busy} onClick={() => void perform(async () => {
            setIssued(await adminScreens.create(eventId, ttl))
          }, true)}>创建大屏链接</Button>
        </Space>
        <p>有效授权 {activeCount} / 20。链接仅供展示设备使用，可单独撤销。</p>
      </Card>
      {issued && <Card size="small" title="新建链接 · 仅本次可见">
        <Alert type="info" title="请复制到展示设备后再关闭" description="链接只能读取公开展示数据。刷新大屏页面后，需使用完整链接重新打开；请保存原链接。" />
        <Typography.Paragraph copyable={{ text: link }} className="screen-issued-link">{link}</Typography.Paragraph>
        <Space wrap><a href={link} target="_blank" rel="noopener noreferrer"><Button>打开大屏</Button></a>
          <Button onClick={() => setIssued(null)}>已保存，隐藏链接</Button></Space>
      </Card>}
      <section aria-label="大屏授权列表"><h3>授权列表</h3>
        {snapshot.screen_grants.length === 0 && <p>暂无大屏授权。</p>}
        <ul className="screen-grant-list">{snapshot.screen_grants.map(grant => {
          const expired = Date.parse(grant.expires_at) <= now
          return <li key={grant.id}>
            <div><Typography.Text code>{grant.id}</Typography.Text><Tag color={grant.revoked_at || expired ? 'default' : 'green'}>{grant.revoked_at ? '已撤销' : expired ? '已到期' : '有效'}</Tag></div>
            <p>创建 {formatTime(grant.created_at)} · 到期 {formatTime(grant.expires_at)}</p>
            {!grant.revoked_at && !expired && <Button danger disabled={busy} onClick={() => setRevokeId(grant.id)}>撤销授权 {grant.id.slice(0, 8)}</Button>}
          </li>
        })}</ul>
        <Button disabled={busy} onClick={() => void refresh()}>刷新授权与展示状态</Button>
      </section>
    </Space>
    {edit && <DisplayEditor initial={edit} snapshot={snapshot} busy={busy} onClose={() => setEdit(null)} onSave={body => void perform(async () => {
      await adminScreens.display(eventId, body); setEdit(null)
    })} />}
    <Modal title="撤销此大屏授权？" open={!!revokeId} okText="确认撤销" cancelText="取消" okButtonProps={{ danger: true }} confirmLoading={busy}
      onCancel={() => { if (!busy) setRevokeId(null) }} onOk={() => void perform(async () => {
        await adminScreens.revoke(eventId, revokeId!); if (issued?.id === revokeId) setIssued(null); setRevokeId(null)
      })}>
      <p>使用该链接的大屏将在下一次同步时失去访问权限。其他授权不受影响。</p>
    </Modal>
  </Drawer>
}

function DisplayEditor({ initial, snapshot, busy, onClose, onSave }: {
  initial: ScreenSettings; snapshot: ConsoleSnapshot; busy: boolean; onClose: () => void; onSave: (body: ScreenSettings) => void
}) {
  const [form] = Form.useForm<ScreenSettings>()
  const mode = Form.useWatch('mode', form) ?? initial.mode
  const needsRound = ['progress', 'paused', 'result'].includes(mode)
  const requiredStatus = { progress: 'OPEN', paused: 'PAUSED', result: 'PUBLISHED' }[mode as 'progress' | 'paused' | 'result']
  const eligible = snapshot.rounds.filter(r => r.status === requiredStatus)
  const ended = snapshot.event.status === 'FINISHED' || snapshot.event.status === 'ARCHIVED'
  return <Modal open title="编辑大屏展示" okText="应用到大屏" cancelText="取消" onCancel={() => { if (!busy) onClose() }} onOk={() => form.submit()} confirmLoading={busy}>
    <Form form={form} layout="vertical" initialValues={initial} onFinish={values => onSave({ ...values, expected_version: initial.expected_version, round_id: needsRound ? values.round_id : null })}>
      <Form.Item name="mode" label="展示模式" rules={[{ required: true }]}>
        <Select onChange={() => form.setFieldValue('round_id', undefined)} options={Object.entries(screenModeLabels).map(([value, label]) => ({ value, label, disabled: value === 'ended' && !ended }))} />
      </Form.Item>
      {needsRound && <Form.Item name="round_id" label="展示对象" rules={[{ required: true, message: '请选择符合当前展示模式的对象' }, {
        validator: (_, value) => eligible.some(r => r.id === value) ? Promise.resolve() : Promise.reject(new Error('对象状态已变化，请重新选择')),
      }]}><Select placeholder="选择对象" options={eligible.map(r => ({ value: r.id, label: `${r.number} · ${r.name}` }))} /></Form.Item>}
      <Form.Item name="title" label="大屏标题" rules={[{ max: 80, message: '标题最多 80 字' }]}><Input maxLength={80} placeholder="留空使用活动标题" /></Form.Item>
      <Form.Item name="theme" label="主题" rules={[{ required: true }]}><Select options={[{ value: 'light', label: '浅色' }, { value: 'dark', label: '深色' }]} /></Form.Item>
      <Form.Item name="show_public_qr" label="显示公共加入二维码" valuePropName="checked"><Switch /></Form.Item>
      <Form.Item name="leaderboard_limit" label="排行榜展示数量" rules={[{ required: true, type: 'integer', min: 1, max: 10000, message: '请输入 1～10000 的整数' }]}><InputNumber min={1} max={10000} precision={0} /></Form.Item>
      <Typography.Paragraph type="secondary">排行榜仅含已公布对象，较长榜单自动分页轮播。保存会校验打开表单时的活动版本，冲突后需重新确认。</Typography.Paragraph>
    </Form>
  </Modal>
}
