import { useState } from 'react'
import { App, Button, Flex, Form, Input, Modal, Radio, Space, Table, Tag, Tooltip, Typography } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useMutation } from '@tanstack/react-query'
import { adminEvents } from '../../api/admin'
import type { EventInfo, JudgeInfo } from '../../api/types'
import { formatTime } from '../format'
import { QueryFailure, useReportError } from '../session'
import { CredentialDialog, type IssuedCredential } from './CredentialDialog'
import { useJudges, useRefreshEvent } from './data'
import { nextNumber, numberRules, trimmedMax } from './fields'

interface JudgeValues {
  number: string
  name: string
}

interface CredentialValues {
  source: 'generated' | 'manual'
  code?: string
  reason?: string
}

/** 与后端规范化一致：去首尾空白后 8～32 位 ASCII 字母数字，至少各含一个字母和数字，统一大写。 */
export function credentialError(value: string): string | null {
  const code = value.trim()
  if (!/^[A-Za-z0-9]{8,32}$/.test(code)) return '身份码为 8～32 位英文字母或数字'
  if (!/[A-Za-z]/.test(code) || !/[0-9]/.test(code)) return '身份码须同时包含字母和数字'
  return null
}

export function JudgesPanel({ event, editable }: { event: EventInfo; editable: boolean }) {
  const eventId = event.id
  const judges = useJudges(eventId)
  const refresh = useRefreshEvent(eventId)
  const report = useReportError()
  const { message, modal } = App.useApp()
  const [editing, setEditing] = useState<JudgeInfo | 'new' | null>(null)
  const [credentialFor, setCredentialFor] = useState<JudgeInfo | null>(null)
  const [issued, setIssued] = useState<IssuedCredential[] | null>(null)
  const [judgeForm] = Form.useForm<JudgeValues>()
  const [credentialForm] = Form.useForm<CredentialValues>()
  const list = judges.data ?? []
  const resettable = event.status === 'READY' || event.status === 'RUNNING'

  const save = useMutation({
    mutationFn: ({ target, values }: { target: JudgeInfo | 'new'; values: JudgeValues }) => {
      const body = { number: values.number.trim(), name: values.name.trim() }
      return target === 'new' ? adminEvents.createJudge(eventId, body) : adminEvents.patchJudge(eventId, target.id, body)
    },
    onSuccess: (_, { target }) => {
      message.success(target === 'new' ? '已添加评委' : '已保存')
      setEditing(null)
      void refresh()
    },
    onError: error => {
      const info = report(error, '保存失败')
      if (info.code === 'NUMBER_CONFLICT') judgeForm.setFields([{ name: 'number', errors: ['编号已被本活动其他评委使用'] }])
      else if (info.action !== 'fix') {
        setEditing(null)
        void refresh()
      }
    },
  })

  const remove = useMutation({
    mutationFn: (judge: JudgeInfo) => adminEvents.removeJudge(eventId, judge.id),
    onSuccess: () => {
      message.success('已删除')
      void refresh()
    },
    onError: error => {
      report(error, '删除失败')
      void refresh()
    },
  })

  const credential = useMutation({
    // 响应含明文：交给对话框状态后即从变更缓存移除。
    gcTime: 0,
    mutationFn: ({ judge, values }: { judge: JudgeInfo; values: CredentialValues }) => {
      const code = values.source === 'manual' ? (values.code ?? '').trim() : null
      return resettable
        ? adminEvents.resetCredential(eventId, judge.id, (values.reason ?? '').trim(), code)
        : adminEvents.setCredential(eventId, judge.id, code)
    },
    onSuccess: (result, { judge }) => {
      setCredentialFor(null)
      credentialForm.resetFields()
      setIssued([{ result, number: judge.number, name: judge.name }])
      credential.reset()
      void refresh()
    },
    onError: error => {
      const info = report(error, resettable ? '重置失败' : '设置失败')
      if (info.code === 'CREDENTIAL_CONFLICT') {
        credentialForm.setFields([{ name: 'code', errors: ['与本活动其他评委的身份码重复'] }])
      } else if (info.code === 'CREDENTIAL_UNCHANGED') {
        credentialForm.setFields([{ name: 'code', errors: ['新身份码不能与当前身份码相同'] }])
      } else if (info.action !== 'fix') {
        // 无幂等键：结果未知时不重发；若已生效，明文无法找回，只能再次设置或重置。
        setCredentialFor(null)
        void refresh()
        if (info.action === 'verify') {
          modal.warning({
            title: '身份码操作结果未知',
            content: '请查看该评委的凭证版本与更新时间。若已更新，明文无法找回，需要再次设置或重置后分发。',
          })
        }
      }
    },
  })

  const openJudge = (target: JudgeInfo | 'new') => {
    judgeForm.resetFields()
    judgeForm.setFieldsValue(target === 'new' ? { number: nextNumber(list.map(j => j.number)), name: '' } : target)
    setEditing(target)
  }

  const openCredential = (judge: JudgeInfo) => {
    credentialForm.resetFields()
    credentialForm.setFieldsValue({ source: 'generated', code: '', reason: '' })
    setCredentialFor(judge)
  }

  const source = Form.useWatch('source', credentialForm)
  if (judges.isError) return <QueryFailure error={judges.error} onRetry={() => void judges.refetch()} />

  const missing = list.filter(j => !j.credential_is_set).length

  return (
    <>
      <Flex justify="space-between" align="center" wrap gap={12} className="panel-toolbar">
        <Typography.Text type="secondary">
          共 {list.length} 位评委
          {event.status === 'DRAFT' && missing > 0 && `，${missing} 位未设置身份码（发布时自动生成并仅显示一次）`}
          。身份码明文不保存在页面中，只在设置、生成或重置时显示一次。
        </Typography.Text>
        {editable && <Button type="primary" icon={<PlusOutlined />} onClick={() => openJudge('new')}>添加评委</Button>}
      </Flex>
      <Table<JudgeInfo>
        rowKey="id"
        dataSource={list}
        loading={judges.isPending}
        pagination={false}
        size="middle"
        locale={{ emptyText: '还没有评委，发布前至少需要一位' }}
        columns={[
          { title: '编号', dataIndex: 'number', width: 120 },
          { title: '姓名', dataIndex: 'name' },
          {
            title: '身份码',
            render: (_, j) =>
              j.credential_is_set ? (
                <Space size={4} wrap>
                  <Tag color="green">已设置</Tag>
                  <Typography.Text type="secondary">
                    {j.credential_source === 'manual' ? '手动' : '自动'} · 第 {j.credential_version} 版 · {formatTime(j.credential_updated_at)}
                  </Typography.Text>
                </Space>
              ) : (
                <Tag>未设置</Tag>
              ),
          },
          {
            title: '操作',
            width: 220,
            render: (_, judge) => (
              <Space size={0} wrap>
                {editable && (
                  <>
                    <Button size="small" type="link" onClick={() => openCredential(judge)}>
                      {judge.credential_is_set ? '重新设置身份码' : '设置身份码'}
                    </Button>
                    <Button size="small" type="link" onClick={() => openJudge(judge)}>编辑</Button>
                    <Button
                      size="small"
                      type="link"
                      danger
                      onClick={() =>
                        modal.confirm({
                          title: `删除评委“${judge.number} ${judge.name}”？`,
                          okText: '删除',
                          okButtonProps: { danger: true },
                          onOk: () => remove.mutateAsync(judge).catch(() => undefined),
                        })
                      }
                    >
                      删除
                    </Button>
                  </>
                )}
                {resettable && (
                  <Tooltip title="换手机或身份码泄露时使用：撤销该评委的旧会话，评分记录保持不变">
                    <Button size="small" type="link" onClick={() => openCredential(judge)}>重置身份码</Button>
                  </Tooltip>
                )}
              </Space>
            ),
          },
        ]}
      />

      <Modal
        open={editing !== null}
        title={editing === 'new' ? '添加评委' : '编辑评委'}
        okText="保存"
        confirmLoading={save.isPending}
        onCancel={() => setEditing(null)}
        onOk={() => judgeForm.submit()}
        forceRender
      >
        <Form<JudgeValues> form={judgeForm} layout="vertical" onFinish={values => editing && save.mutate({ target: editing, values })}>
          <Form.Item label="编号" name="number" rules={numberRules('评委')} extra="用于展示与排序，不能作为身份码">
            <Input maxLength={32} />
          </Form.Item>
          <Form.Item label="姓名" name="name" rules={[{ required: true, whitespace: true, message: '请填写姓名' }, trimmedMax(80, '姓名')]}>
            <Input maxLength={80} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={credentialFor !== null}
        title={credentialFor && `${resettable ? '重置' : '设置'}身份码：${credentialFor.number} ${credentialFor.name}`}
        okText={resettable ? '确认重置' : '确定'}
        okButtonProps={{ danger: resettable }}
        confirmLoading={credential.isPending}
        onCancel={() => setCredentialFor(null)}
        onOk={() => credentialForm.submit()}
        forceRender
      >
        <Form<CredentialValues>
          form={credentialForm}
          layout="vertical"
          onFinish={values => credentialFor && credential.mutate({ judge: credentialFor, values })}
        >
          {resettable ? (
            <Typography.Paragraph type="warning">重置后旧身份码立即失效，该评委已登录的设备会被退出；评委 ID、姓名、编号和已交评分不变。</Typography.Paragraph>
          ) : (
            credentialFor?.credential_is_set && (
              <Typography.Paragraph type="warning">将替换该评委当前的身份码，旧码随即失效。</Typography.Paragraph>
            )
          )}
          <Form.Item name="source">
            <Radio.Group
              options={[
                { value: 'generated', label: '自动生成（12 位易读字母数字）' },
                { value: 'manual', label: '手动设置' },
              ]}
            />
          </Form.Item>
          {source === 'manual' && (
            <Form.Item
              label="身份码"
              name="code"
              rules={[
                {
                  validator: (_, value?: string) => {
                    const problem = credentialError(value ?? '')
                    return problem ? Promise.reject(new Error(problem)) : Promise.resolve()
                  },
                },
              ]}
              extra="8～32 位，须同时包含字母和数字，不区分大小写；不能与本活动其他评委重复"
            >
              <Input maxLength={32} autoComplete="off" spellCheck={false} />
            </Form.Item>
          )}
          {resettable && (
            <Form.Item
              label="重置原因"
              name="reason"
              rules={[{ required: true, whitespace: true, message: '请填写重置原因' }, trimmedMax(500, '原因')]}
            >
              <Input.TextArea maxLength={500} autoSize={{ minRows: 2 }} placeholder="如：更换手机" />
            </Form.Item>
          )}
        </Form>
      </Modal>

      {issued && (
        <CredentialDialog
          title={resettable ? '新的身份码' : '身份码已设置'}
          items={issued}
          publicCode={event.public_code}
          onClose={() => setIssued(null)}
        />
      )}
    </>
  )
}
