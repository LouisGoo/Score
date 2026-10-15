import { useCallback, useEffect, useRef, useState } from 'react'
import { useLoaderData } from 'react-router'
import { Button, Modal, QRCode } from 'antd'
import { ApiError } from '../api/client'
import { describeError } from '../api/errors'
import { publicEntryUrl } from '../lib/screen'
import { useNow } from '../lib/useNow'
import { invalidGrant, useScreenSnapshot } from './data'
import type { ScreenAccess } from './access'
import { ScreenContent } from './ScreenContent'
import './screen.css'

export function ScreenPage() {
  const access = useLoaderData() as ScreenAccess
  return <ScreenSession key={access.grantId} access={access} />
}

function ScreenSession({ access }: { access: ScreenAccess }) {
  const [revoked, setRevoked] = useState(false)
  const revoke = useCallback(() => setRevoked(true), [])
  if (revoked) return <RevokedScreen />
  return access.token ? <ScreenFeed access={access as ScreenAccess & { token: string }} onInvalid={revoke} />
    : <AccessNotice title="请使用完整的大屏链接" detail="请向主办方获取只读展示链接。刷新后需用原完整链接重新打开。" />
}

function AccessNotice({ title, detail }: { title: string; detail: string }) {
  return <main className="score-screen screen-access" data-theme="dark"><p className="screen-eyebrow">现场大屏</p><h1>{title}</h1><p>{detail}</p></main>
}

function ScreenFeed({ access, onInvalid }: { access: ScreenAccess & { token: string }; onInvalid: () => void }) {
  const query = useScreenSnapshot(access.grantId, access.token)
  const now = useNow(true, 1000)
  const [qrOpen, setQrOpen] = useState(false)
  const [fullscreen, setFullscreen] = useState(false)
  const [fullscreenError, setFullscreenError] = useState('')
  const root = useRef<HTMLElement>(null)
  useEffect(() => { if (invalidGrant(query.error)) onInvalid() }, [query.error, onInvalid])
  useEffect(() => {
    const update = () => setFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', update)
    return () => document.removeEventListener('fullscreenchange', update)
  }, [])
  async function toggleFullscreen() {
    setFullscreenError('')
    try {
      if (document.fullscreenElement) await document.exitFullscreen()
      else if (root.current?.requestFullscreen) await root.current.requestFullscreen()
      else setFullscreenError('此浏览器不支持网页全屏，可使用浏览器或投影设备的全屏功能。')
    } catch { setFullscreenError('未能进入全屏，请再次点击或使用浏览器的全屏功能。') }
  }

  // Never keep a once-authorized picture on screen after authorization is rejected.
  if (invalidGrant(query.error)) return <RevokedScreen />
  const data = query.data
  const error = query.error ? describeError(query.error) : null
  const retryAt = query.error instanceof ApiError ? query.errorUpdatedAt + (query.error.retryAfter ?? 0) * 1000 : 0
  const retryDisabled = query.isFetching || retryAt > now
  const stale = query.isError || query.syncStatus === 'offline' || query.syncStatus === 'recovering' || query.fetchStatus === 'paused' || (data && now - query.verifiedAt > 45000)
  const joinUrl = data ? publicEntryUrl(data.event.public_code) : ''
  return <main ref={root} className="score-screen" data-theme={data?.display.theme ?? 'dark'}>
    <header className="screen-header"><div><p className="screen-eyebrow">{data?.event.organization || '现场评分'}</p>
      <h1>{data?.display.title || data?.event.title || '现场大屏'}</h1></div>
      <div className="screen-tools"><button type="button" onClick={() => void toggleFullscreen()}>{fullscreen ? '退出全屏' : '全屏显示'}</button></div>
    </header>
    {fullscreenError && <p className="screen-message" role="status">{fullscreenError}</p>}
    {data ? <div className={`screen-body ${data.display.show_public_qr ? 'with-qr' : ''}`}>
      <ScreenContent snapshot={data} now={now} />
      {data.display.show_public_qr && <aside className="screen-join">
        <button className="screen-qr-button" type="button" aria-label="放大公共加入二维码" onClick={() => setQrOpen(true)}>
          <QRCode type="svg" value={joinUrl} size={220} color="#172e29" bgColor="#ffffff" bordered={false} />
        </button>
        <h2>扫码加入活动</h2><p>活动码</p><strong className="screen-public-code">{data.event.public_code}</strong>
        <p className="screen-hint">评委请使用主办方提供的身份码</p>
      </aside>}
    </div> : <section className="screen-empty"><h2>{query.isPending && !stale ? '正在连接现场大屏' : '暂时无法加载展示内容'}</h2><p>连接恢复后将自动同步。</p></section>}
    <footer className="screen-footer">
      <div role="status"><span className={`screen-dot ${stale ? 'delayed' : ''}`} aria-hidden="true" />{stale ? '连接中，数据可能延迟' : data ? '已同步' : '连接中'}
        {data && <span> · 最后同步 <time dateTime={data.server_time}>{new Date(data.server_time).toLocaleTimeString('zh-CN', { hour12: false })}</time></span>}
        {error && <span className="screen-error-detail">{error.message}{error.requestId ? ` · 请求编号 ${error.requestId}` : ''}</span>}
      </div>
      <button type="button" disabled={retryDisabled} onClick={() => void query.refetch()}>{retryAt > now ? '稍后重试' : '重新同步'}</button>
    </footer>
    {data?.display.show_public_qr && <Modal open={qrOpen} title="扫码加入活动" onCancel={() => setQrOpen(false)} footer={<Button onClick={() => setQrOpen(false)}>关闭</Button>}
      width={560} className="screen-qr-dialog" getContainer={() => root.current ?? document.body}>
      <QRCode type="svg" value={joinUrl} size={420} color="#172e29" bgColor="#ffffff" />
      <p>活动码：<strong>{data.event.public_code}</strong></p><p className="screen-public-url">{joinUrl}</p>
    </Modal>}
  </main>
}

/** Unmount the query after revocation to release both its data and token-bearing query closure. */
function RevokedScreen() {
  return <AccessNotice title="大屏授权已失效" detail="授权可能已到期或被主办方撤销。请联系主办方获取新的完整链接。" />
}
