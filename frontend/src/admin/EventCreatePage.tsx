import { App, Button, Card, Checkbox, Form, Space, Steps, Typography } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router'
import { adminEvents } from '../api/admin'
import { queryKeys } from '../api/query'
import { BasicFields, basicPayload, toBasicValues, type BasicValues } from './EventBasicFields'
import { DEFAULT_RULE } from './rule'
import { useAdminSession, useReportError } from './session'
import { SETUP_STEPS } from './settings/steps'

type CreateValues = BasicValues & { useDefaultRule: boolean }

export function EventCreatePage() {
  const { admin } = useAdminSession()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const report = useReportError()
  const { modal } = App.useApp()
  const [form] = Form.useForm<CreateValues>()

  const create = useMutation({
    mutationFn: (values: CreateValues) =>
      adminEvents.create({ ...basicPayload(values), scoring_rule: values.useDefaultRule ? DEFAULT_RULE : null }),
    onSuccess: event => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.adminEvents(admin.id) })
      navigate(`/admin/events/${event.id}/settings?tab=entries`, { replace: true })
    },
    onError: error => {
      const info = report(error, '创建失败')
      // 创建无幂等键：结果未知时引导先核对列表，避免重复创建。
      if (info.action === 'verify' || info.code === 'SERVICE_UNAVAILABLE') {
        void queryClient.invalidateQueries({ queryKey: queryKeys.adminEvents(admin.id) })
        modal.warning({
          title: '创建结果未知',
          content: '请求可能已在服务端完成。请先到活动列表核对是否已出现该活动，再决定是否重新创建。',
          okText: '去活动列表',
          onOk: () => navigate('/admin/events'),
        })
      }
    },
  })

  return (
    <>
      <Typography.Title level={3} className="page-heading">创建活动</Typography.Title>
      <Steps current={0} items={SETUP_STEPS.map(s => ({ title: s.title }))} className="setup-steps" size="small" />
      <Card>
        <Form<CreateValues>
          form={form}
          layout="vertical"
          initialValues={{ ...toBasicValues(), useDefaultRule: true }}
          disabled={create.isPending}
          onFinish={values => create.mutate(values)}
          scrollToFirstError
        >
          <BasicFields />
          <Form.Item name="useDefaultRule" valuePropName="checked">
            <Checkbox>使用默认评分规则：单项总分，满分 100、步长 0.1，平均分（可在“评分规则”中修改）</Checkbox>
          </Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" loading={create.isPending}>创建并继续录入名单</Button>
            <Link to="/admin/events"><Button>取消</Button></Link>
          </Space>
        </Form>
      </Card>
    </>
  )
}
