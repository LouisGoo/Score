import { Pending } from '../components/Pending'

/** 只读大屏：独立页面，不包含任何管理按钮或凭证。 */
export function ScreenPage() {
  return (
    <div className="screen-layout">
      <Pending title="现场大屏" batch="17" />
    </div>
  )
}
