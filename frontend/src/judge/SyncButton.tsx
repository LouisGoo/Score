import { useEffect, useState, type CSSProperties } from 'react'
import { Button } from 'antd'

const LAP_MS = 1000

export function SyncButton({ fetching, onSync }: { fetching: boolean; onSync: () => void }) {
  const [sync, setSync] = useState({ fetching, cycle: fetching ? 1 : 0 })
  const [finishedCycle, setFinishedCycle] = useState(0)
  if (sync.fetching !== fetching) {
    setSync({ fetching, cycle: sync.cycle + (fetching ? 1 : 0) })
  }

  // CSS animation events may be cancelled or omitted. Each request owns a cleanup deadline.
  useEffect(() => {
    if (!sync.cycle) return
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const timer = window.setTimeout(() => setFinishedCycle(sync.cycle), reducedMotion ? 0 : LAP_MS)
    return () => window.clearTimeout(timer)
  }, [sync.cycle])

  const active = fetching || sync.cycle > finishedCycle
  return <Button className="judge-sync-button" loading={active} aria-busy={fetching} onClick={onSync}
    style={{ '--judge-sync-duration': `${LAP_MS}ms` } as CSSProperties}>
    <span>同步状态</span>
    {active && <span key={sync.cycle} className="judge-sync-border" aria-hidden="true" />}
  </Button>
}
