import { Result } from 'antd'

/** 已规划路由的占位页，标明交付批次，避免误以为功能已可用。 */
export function Pending({ title, batch }: { title: string; batch: string }) {
  return <Result status="info" title={title} subTitle={`该页面将在 ${batch} 批次实现`} />
}
