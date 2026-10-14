import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// antd 的响应式栅格依赖 matchMedia，jsdom 未实现。
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList
}

// antd 的 Tabs、Table 等依赖 ResizeObserver，jsdom 未实现。
if (!window.ResizeObserver) {
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
}

// QRCode 绘制到 canvas；jsdom 无 canvas 实现，测试中只验证是否渲染。
HTMLCanvasElement.prototype.getContext = (() => null) as unknown as HTMLCanvasElement['getContext']

afterEach(() => {
  cleanup()
  localStorage.clear()
})
