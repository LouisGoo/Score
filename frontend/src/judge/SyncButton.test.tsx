import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SyncButton } from './SyncButton'

beforeEach(() => { vi.useFakeTimers() })
afterEach(() => { vi.useRealTimers() })
const advance = (ms: number) => act(() => vi.advanceTimersByTime(ms))

it('clears the border after every automatic sync even without animationend events', () => {
  const onSync = vi.fn()
  const view = render(<SyncButton fetching={false} onSync={onSync} />)
  for (let cycle = 0; cycle < 6; cycle++) {
    view.rerender(<SyncButton fetching onSync={onSync} />)
    advance(20)
    view.rerender(<SyncButton fetching={false} onSync={onSync} />)
    expect(view.container.querySelector('.judge-sync-border')).not.toBeNull()
    advance(980)
    expect(view.container.querySelector('.judge-sync-border')).toBeNull()
  }
  fireEvent.click(screen.getByRole('button', { name: /同步状态/ }))
  expect(onSync).toHaveBeenCalledOnce()
})

it('gives a consecutive request its own lap and ignores stale animation events', () => {
  const onSync = vi.fn()
  const view = render(<SyncButton fetching onSync={onSync} />)
  const firstBorder = view.container.querySelector('.judge-sync-border')!
  advance(800)
  view.rerender(<SyncButton fetching={false} onSync={onSync} />)
  view.rerender(<SyncButton fetching onSync={onSync} />)
  const secondBorder = view.container.querySelector('.judge-sync-border')!
  expect(secondBorder).not.toBe(firstBorder)
  view.rerender(<SyncButton fetching={false} onSync={onSync} />)
  fireEvent.animationEnd(firstBorder, { animationName: 'judge-sync-flow' })
  advance(200)
  expect(view.container.querySelector('.judge-sync-border')).toBe(secondBorder)
  advance(800)
  expect(view.container.querySelector('.judge-sync-border')).toBeNull()
})

it('keeps a slow request busy after one lap and restores the border when it settles', () => {
  const onSync = vi.fn()
  const view = render(<SyncButton fetching onSync={onSync} />)
  advance(2000)
  expect(view.container.querySelector('.judge-sync-border')).not.toBeNull()
  fireEvent.click(screen.getByRole('button', { name: /同步状态/ }))
  expect(onSync).not.toHaveBeenCalled()
  view.rerender(<SyncButton fetching={false} onSync={onSync} />)
  expect(view.container.querySelector('.judge-sync-border')).toBeNull()
})

it('does not wait for a visual lap when reduced motion is enabled', () => {
  vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: true } as MediaQueryList)
  const onSync = vi.fn()
  const view = render(<SyncButton fetching onSync={onSync} />)
  view.rerender(<SyncButton fetching={false} onSync={onSync} />)
  advance(0)
  expect(view.container.querySelector('.judge-sync-border')).toBeNull()
})

