import { App, Button, Layout, Space, Typography } from 'antd'
import { LogoutOutlined } from '@ant-design/icons'
import { useMutation } from '@tanstack/react-query'
import { Link, Outlet, useNavigate } from 'react-router'
import { adminAuth } from '../api/admin'
import { LOGIN_PATH, useForgetAdmin, useSessionQuery } from './session'

export { AdminGuard } from './session'
export { LoginPage } from './LoginPage'
export { EventListPage } from './EventListPage'
export { EventCreatePage } from './EventCreatePage'
export { EventSettingsPage } from './settings/EventSettingsPage'
export { EventControlPage } from './control/EventControlPage'
export { EventResultsPage } from './control/EventResultsPage'

/** 主办方模块入口：仅在访问 /admin 时加载，手机评委端不下载此分包。 */
export function AdminLayout() {
  return (
    <Layout className="admin-layout">
      <Layout.Header className="admin-header">
        <Link to="/admin/events">
          <Typography.Text strong className="brand">在线打分系统 · 主办方</Typography.Text>
        </Link>
        <AccountMenu />
      </Layout.Header>
      <Layout.Content className="admin-content">
        <Outlet />
      </Layout.Content>
    </Layout>
  )
}

/** 只读取 AdminGuard 已恢复的会话，不在此单独请求。 */
function AccountMenu() {
  const navigate = useNavigate()
  const forget = useForgetAdmin()
  const { message } = App.useApp()
  const session = useSessionQuery({ enabled: false })
  const logout = useMutation({
    mutationFn: () => adminAuth.logout(),
    onSettled: (_, error) => {
      // 退出请求失败时本地仍清空身份，服务端会话到期自然失效。
      if (error) message.warning('已在本机退出；服务端会话未能确认撤销')
      forget()
      navigate(LOGIN_PATH, { replace: true })
    },
  })
  if (!session.data) return null
  return (
    <Space className="account">
      <Typography.Text className="account-name">{session.data.admin.login}</Typography.Text>
      <Button type="text" className="account-logout" icon={<LogoutOutlined />} loading={logout.isPending} onClick={() => logout.mutate()}>
        退出
      </Button>
    </Space>
  )
}