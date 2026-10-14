import { Button, Card, Col, Row, Space, Tag, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { request } from '../api/client'

function useLiveness() {
  return useQuery({
    queryKey: ['health', 'live'],
    queryFn: async ({ signal }) => {
      const body = await request<{ status?: unknown }>('/health/live', { signal, timeoutMs: 5000 })
      if (body.status !== 'ok') throw new Error('Unexpected response')
      return true
    },
    retry: false,
    refetchOnWindowFocus: false,
  })
}

const modules = [
  { label: '01 / 主持人', title: '掌握活动进程', text: '配置活动与名单，控制开评、收评和成绩公布。', to: '/admin/login', action: '主办方登录' },
  { label: '02 / 评委', title: '专注每次评分', text: '手机加入活动，确认评分，查看提交回执。', to: '/join', action: '评委加入' },
  { label: '03 / 大屏', title: '呈现现场结果', text: '展示评分进度、已公布成绩与排行榜，由主持人生成专用链接。' },
]

export function Home() {
  const live = useLiveness()
  return (
    <main className="home">
      <Typography.Text className="eyebrow">在线打分系统</Typography.Text>
      <Typography.Title className="home-title">让每一份评分，<br />都有据可循。</Typography.Title>
      <Typography.Paragraph type="secondary" className="home-intro">
        面向比赛、答辩与项目评审，连接主持人、评委和现场大屏。
      </Typography.Paragraph>
      <Row gutter={[24, 24]} className="home-modules">
        {modules.map(m => (
          <Col xs={24} md={8} key={m.label}>
            <Card variant="borderless" className="home-card">
              <Typography.Text type="secondary">{m.label}</Typography.Text>
              <Typography.Title level={4}>{m.title}</Typography.Title>
              <Typography.Paragraph type="secondary">{m.text}</Typography.Paragraph>
              {m.to && <Link to={m.to}><Button>{m.action}</Button></Link>}
            </Card>
          </Col>
        ))}
      </Row>
      <Space role="status" wrap>
        {live.isPending && <Tag>正在检查服务连接…</Tag>}
        {live.isSuccess && <Tag color="success">服务已连接</Tag>}
        {live.isError && (
          <>
            <Tag color="error">暂时无法连接服务，请稍后重试</Tag>
            <Button size="small" onClick={() => void live.refetch()}>重新连接</Button>
          </>
        )}
      </Space>
    </main>
  )
}
