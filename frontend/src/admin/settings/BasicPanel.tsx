import { useEffect } from 'react'
import { App, Button, Form, Space } from 'antd'
import { useMutation } from '@tanstack/react-query'
import type { EventInfo } from '../../api/types'
import { adminEvents } from '../../api/admin'
import { BasicFields, basicPatch, toBasicValues, type BasicValues } from '../EventBasicFields'
import { useReportError } from '../session'
import { useRefreshEvent } from './data'

export function BasicPanel({ event, editable }: { event: EventInfo; editable: boolean }) {
  const [form] = Form.useForm<BasicValues>()
  const { message } = App.useApp()
  const report = useReportError()
  const refresh = useRefreshEvent(event.id)

  // 服务端数据更新（保存成功或刷新）后重置表单为最新值。
  useEffect(() => {
    form.setFieldsValue(toBasicValues(event))
  }, [event, form])

  const save = useMutation({
    mutationFn: (values: BasicValues) => {
      const patch = basicPatch(event, values)
      return Object.keys(patch).length ? adminEvents.patch(event.id, patch) : Promise.resolve(null)
    },
    onSuccess: result => {
      message.success(result ? '已保存' : '没有需要保存的修改')
      if (result) void refresh()
    },
    onError: error => {
      if (report(error, '保存失败').action !== 'fix') void refresh()
    },
  })

  return (
    <Form<BasicValues>
      form={form}
      layout="vertical"
      initialValues={toBasicValues(event)}
      disabled={!editable || save.isPending}
      onFinish={values => save.mutate(values)}
      scrollToFirstError
    >
      <BasicFields />
      {editable && (
        <Space>
          <Button type="primary" htmlType="submit" loading={save.isPending}>保存</Button>
          <Button onClick={() => form.setFieldsValue(toBasicValues(event))}>还原</Button>
        </Space>
      )}
    </Form>
  )
}
