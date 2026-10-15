import { Outlet } from 'react-router'
import { ConfigProvider } from 'antd'
import './judge.css'

/** 评委手机模块：窄屏单列布局，不依赖管理端表格等组件。 */
export function JudgeLayout() {
  return (
    <ConfigProvider theme={{ token: {
      colorPrimary: '#1a5c3a',
      colorLink: '#1a5c3a',
      colorText: '#0f1f16',
      colorTextSecondary: '#52665a',
      borderRadius: 14,
      fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif',
    } }}>
      <div className="judge-surface">
        <div className="judge-backdrop" aria-hidden="true">
          <span className="judge-blob judge-blob-a" />
          <span className="judge-blob judge-blob-b" />
          <span className="judge-blob judge-blob-c" />
        </div>
        <div className="judge-layout"><Outlet /></div>
      </div>
    </ConfigProvider>
  )
}

export { JoinPage } from './JoinPage'
export { JudgeEventPage, JudgeHistoryPage } from './JudgeEventPage'
