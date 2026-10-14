import { Button, Result } from 'antd'
import { Link } from 'react-router'
import { describeError } from '../../api/errors'
import { QueryFailure } from '../session'

/** 快照首次读取失败：草稿没有控制台，引导回设置页发布；其余显示错误并可重试。 */
export function SnapshotFailure({ eventId, error, onRetry }: { eventId: string; error: unknown; onRetry: () => void }) {
  const code = describeError(error).code
  if (code === 'NOT_FOUND') {
    return <Result status="404" title="活动不存在或无权访问" extra={<Link to="/admin/events"><Button>返回活动列表</Button></Link>} />
  }
  if (code === 'EVENT_NOT_PUBLISHED') {
    return (
      <Result
        status="info"
        title="活动尚未发布"
        subTitle="发布后名单与规则冻结，才能进入控制台开评。"
        extra={<Link to={`/admin/events/${eventId}/settings?tab=publish`}><Button type="primary">去发布检查</Button></Link>}
      />
    )
  }
  return <QueryFailure error={error} onRetry={onRetry} />
}
