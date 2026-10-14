import { Outlet } from 'react-router'
import './judge.css'

/** 评委手机模块：窄屏单列布局，不依赖管理端表格等组件。 */
export function JudgeLayout() {
  return (
    <div className="judge-layout">
      <Outlet />
    </div>
  )
}

export { JoinPage } from './JoinPage'
export { JudgeEventPage, JudgeHistoryPage } from './JudgeEventPage'
