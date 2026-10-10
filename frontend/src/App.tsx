import { useEffect, useState } from 'react'

type Connection = 'checking' | 'connected' | 'unavailable'

const labels: Record<Connection, string> = {
  checking: '正在检查服务连接…',
  connected: '服务已连接',
  unavailable: '暂时无法连接服务，请稍后重试',
}

export function App() {
  const [connection, setConnection] = useState<Connection>('checking')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    const timeout = window.setTimeout(() => controller.abort(), 5000)

    async function checkConnection() {
      try {
        const response = await fetch('/api/v1/health/live', {
          signal: controller.signal,
          cache: 'no-store',
        })
        if (!response.ok) throw new Error('Service unavailable')
        const body: unknown = await response.json()
        if (!body || typeof body !== 'object' || !('status' in body) || body.status !== 'ok') {
          throw new Error('Unexpected response')
        }
        if (active) setConnection('connected')
      } catch {
        if (active) setConnection('unavailable')
      } finally {
        window.clearTimeout(timeout)
      }
    }

    void checkConnection()
    return () => {
      active = false
      controller.abort()
      window.clearTimeout(timeout)
    }
  }, [attempt])

  return (
    <main>
      <p className="eyebrow">在线打分系统 · 开发预览</p>
      <h1>让每一份评分，<br />都有据可循。</h1>
      <p className="intro">面向比赛、答辩与项目评审，连接主持人、评委和现场大屏。</p>
      <section className="modules" aria-label="规划中的功能">
        <article><span>01 / 主持人</span><h2>掌握活动进程</h2><p>配置活动与名单，控制开评、收评和成绩公布。</p></article>
        <article><span>02 / 评委</span><h2>专注每次评分</h2><p>手机加入活动，确认评分，查看提交回执。</p></article>
        <article><span>03 / 大屏</span><h2>呈现现场结果</h2><p>展示评分进度、已公布成绩与排行榜。</p></article>
      </section>
      <footer>
        <p>当前为工程初始化版本，评分功能正在建设中。</p>
        <div className="connection">
          <span role="status" data-state={connection}>{labels[connection]}</span>
          {connection === 'unavailable' && (
            <button onClick={() => {
              setConnection('checking')
              setAttempt(value => value + 1)
            }}>重新连接</button>
          )}
        </div>
      </footer>
    </main>
  )
}
