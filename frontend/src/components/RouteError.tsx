import { Button, Result } from 'antd'
import { isRouteErrorResponse, useRouteError } from 'react-router'

/** 路由级错误边界；新版本发布后旧页面加载分包失败时，提示刷新获取最新资源。 */
export function RouteError() {
  const error = useRouteError()
  if (isRouteErrorResponse(error) && error.status === 404) {
    return <Result status="404" title="页面不存在" extra={<Button href="/">返回首页</Button>} />
  }
  return (
    <Result
      status="error"
      title="页面加载失败"
      subTitle="可能是网络中断或系统已更新，请刷新页面重试。"
      extra={<Button type="primary" onClick={() => window.location.reload()}>刷新页面</Button>}
    />
  )
}

export function NotFound() {
  return <Result status="404" title="页面不存在" extra={<Button href="/">返回首页</Button>} />
}
