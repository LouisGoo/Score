import { Layout, Typography } from 'antd'
import { Link, Outlet } from 'react-router'
import { Pending } from '../components/Pending'

/** 主办方模块入口：仅在访问 /admin 时加载，手机评委端不下载此分包。 */
export function AdminLayout() {
  return (
    <Layout className="admin-layout">
      <Layout.Header className="admin-header">
        <Link to="/admin/events">
          <Typography.Text strong className="brand">在线打分系统 · 主办方</Typography.Text>
        </Link>
      </Layout.Header>
      <Layout.Content className="admin-content">
        <Outlet />
      </Layout.Content>
    </Layout>
  )
}

export const LoginPage = () => <Pending title="主办方登录" batch="14b" />
export const EventListPage = () => <Pending title="活动列表" batch="14b" />
export const EventCreatePage = () => <Pending title="创建活动" batch="14b" />
export const EventSettingsPage = () => <Pending title="活动设置" batch="14b" />
export const EventControlPage = () => <Pending title="主持人控制台" batch="15" />
export const EventResultsPage = () => <Pending title="成绩与记录" batch="15" />
