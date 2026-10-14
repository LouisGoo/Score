import { Outlet } from 'react-router'
import { Pending } from '../components/Pending'

/** 评委手机模块：窄屏单列布局，不依赖管理端表格等组件。 */
export function JudgeLayout() {
  return (
    <div className="judge-layout">
      <Outlet />
    </div>
  )
}

export const JoinPage = () => <Pending title="加入活动" batch="16" />
export const JudgeEventPage = () => <Pending title="评分" batch="16" />
export const JudgeHistoryPage = () => <Pending title="本人记录" batch="16" />
