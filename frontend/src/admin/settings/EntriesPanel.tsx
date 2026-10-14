import { useState } from 'react'
import { App, Button, Flex, Form, Input, InputNumber, Modal, Table, Typography } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useMutation } from '@tanstack/react-query'
import { adminEvents } from '../../api/admin'
import type { EntryInfo } from '../../api/types'
import { QueryFailure, useReportError } from '../session'
import { useEntries, useRefreshEvent } from './data'
import { nextNumber, numberRules, trimmedMax } from './fields'

interface EntryValues {
  number: string
  name: string
  description: string
  sort_order: number
}

export function EntriesPanel({ eventId, editable }: { eventId: string; editable: boolean }) {
  const entries = useEntries(eventId)
  const refresh = useRefreshEvent(eventId)
  const report = useReportError()
  const { message, modal } = App.useApp()
  const [editing, setEditing] = useState<EntryInfo | 'new' | null>(null)
  const [form] = Form.useForm<EntryValues>()
  const list = entries.data ?? []

  const save = useMutation({
    mutationFn: ({ target, values }: { target: EntryInfo | 'new'; values: EntryValues }) => {
      const body = {
        number: values.number.trim(),
        name: values.name.trim(),
        description: values.description.trim(),
        sort_order: values.sort_order,
      }
      return target === 'new'
        ? adminEvents.createEntry(eventId, body)
        : adminEvents.patchEntry(eventId, target.id, body)
    },
    onSuccess: (_, { target }) => {
      message.success(target === 'new' ? '已添加对象' : '已保存')
      setEditing(null)
      void refresh()
    },
    onError: error => {
      const info = report(error, '保存失败')
      if (info.code === 'NUMBER_CONFLICT') form.setFields([{ name: 'number', errors: ['编号已被本活动其他对象使用'] }])
      else if (info.action !== 'fix') {
        setEditing(null)
        void refresh()
      }
    },
  })

  const remove = useMutation({
    mutationFn: (entry: EntryInfo) => adminEvents.removeEntry(eventId, entry.id),
    onSuccess: () => {
      message.success('已删除')
      void refresh()
    },
    onError: error => {
      report(error, '删除失败')
      void refresh()
    },
  })

  const open = (target: EntryInfo | 'new') => {
    form.resetFields()
    form.setFieldsValue(
      target === 'new'
        ? {
            number: nextNumber(list.map(e => e.number)),
            name: '',
            description: '',
            sort_order: list.reduce((max, e) => Math.max(max, (e.sort_order ?? 0) + 1), 0),
          }
        : { number: target.number, name: target.name, description: target.description ?? '', sort_order: target.sort_order ?? 0 },
    )
    setEditing(target)
  }

  if (entries.isError) return <QueryFailure error={entries.error} onRetry={() => void entries.refetch()} />

  return (
    <>
      <Flex justify="space-between" align="center" className="panel-toolbar">
        <Typography.Text type="secondary">共 {list.length} 个对象，按展示顺序、编号排列；发布后每个对象生成一个评分任务。</Typography.Text>
        {editable && <Button type="primary" icon={<PlusOutlined />} onClick={() => open('new')}>添加对象</Button>}
      </Flex>
      <Table<EntryInfo>
        rowKey="id"
        dataSource={list}
        loading={entries.isPending}
        pagination={false}
        size="middle"
        locale={{ emptyText: '还没有参评对象，发布前至少需要一个' }}
        columns={[
          { title: '顺序', dataIndex: 'sort_order', width: 80 },
          { title: '编号', dataIndex: 'number', width: 120 },
          { title: '名称', dataIndex: 'name' },
          { title: '简介', dataIndex: 'description', ellipsis: true },
          ...(editable
            ? [
                {
                  title: '操作',
                  width: 140,
                  render: (_: unknown, entry: EntryInfo) => (
                    <>
                      <Button size="small" type="link" onClick={() => open(entry)}>编辑</Button>
                      <Button
                        size="small"
                        type="link"
                        danger
                        onClick={() =>
                          modal.confirm({
                            title: `删除对象“${entry.number} ${entry.name}”？`,
                            okText: '删除',
                            okButtonProps: { danger: true },
                            onOk: () => remove.mutateAsync(entry).catch(() => undefined),
                          })
                        }
                      >
                        删除
                      </Button>
                    </>
                  ),
                },
              ]
            : []),
        ]}
      />
      <Modal
        open={editing !== null}
        title={editing === 'new' ? '添加对象' : '编辑对象'}
        okText="保存"
        confirmLoading={save.isPending}
        onCancel={() => setEditing(null)}
        onOk={() => form.submit()}
        forceRender
      >
        <Form<EntryValues>
          form={form}
          layout="vertical"
          onFinish={values => editing && save.mutate({ target: editing, values })}
        >
          <Form.Item label="编号" name="number" rules={numberRules('对象')} extra="字符串，保留前导零，区分大小写">
            <Input maxLength={32} />
          </Form.Item>
          <Form.Item label="名称" name="name" rules={[{ required: true, whitespace: true, message: '请填写名称' }, trimmedMax(80, '名称')]}>
            <Input maxLength={80} />
          </Form.Item>
          <Form.Item label="简介" name="description" rules={[trimmedMax(2000, '简介')]}>
            <Input.TextArea maxLength={2000} autoSize={{ minRows: 2, maxRows: 6 }} />
          </Form.Item>
          <Form.Item
            label="展示顺序"
            name="sort_order"
            rules={[{ required: true, type: 'integer', min: 0, max: 2147483647, message: '请输入非负整数' }]}
            extra="数字小的先出场；相同时按编号排列"
          >
            <InputNumber min={0} max={2147483647} precision={0} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
