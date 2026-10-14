import type { ReactNode } from 'react'
import { Form, Input, InputNumber, Modal, Space, Switch, Typography } from 'antd'
import { describeError } from '../../api/errors'
import { formatDuration } from '../format'
import { trimmedMax } from '../settings/fields'

export interface ReasonValues {
  /** 去首尾空白；可选原因留空时为 null。 */
  reason: string | null
  /** 仅重开补评使用；null 表示不限时。 */
  durationSeconds: number | null
}

export interface ReasonRequest {
  title: string
  okText: string
  danger?: boolean
  description?: ReactNode
  reasonLabel: string
  /** 为 false 时原因可留空（如已收齐时收评）。 */
  reasonRequired: boolean
  placeholder?: string
  /** 提供时显示评分时长设置（重开补评），值为默认时长，null 为不限时。 */
  duration?: number | null
  submit: (values: ReasonValues) => Promise<unknown>
}

interface FormValues {
  reason: string
  limited: boolean
  duration_seconds: number | null
}

/** 需要填写原因的控制操作；提交失败且需修正输入时保持打开，其余情况关闭并由页面刷新状态。 */
export function ReasonDialog({ request, busy, onClose }: { request: ReasonRequest; busy: boolean; onClose: () => void }) {
  const [form] = Form.useForm<FormValues>()
  const limited = Form.useWatch('limited', form)
  const seconds = Form.useWatch('duration_seconds', form)
  const withDuration = request.duration !== undefined

  const finish = (values: FormValues) => {
    const reason = (values.reason ?? '').trim()
    request
      .submit({
        reason: reason || null,
        durationSeconds: withDuration && values.limited ? values.duration_seconds : null,
      })
      .then(onClose, (error: unknown) => {
        const info = describeError(error)
        if (info.code === 'CLOSE_REASON_REQUIRED') form.setFields([{ name: 'reason', errors: ['未收齐评分，请填写收评原因'] }])
        else if (info.action !== 'fix') onClose()
      })
  }

  return (
    <Modal
      open
      title={request.title}
      okText={request.okText}
      okButtonProps={{ danger: request.danger }}
      confirmLoading={busy}
      onCancel={onClose}
      onOk={() => form.submit()}
      mask={{ closable: false }}
    >
      {request.description && <div className="dialog-description">{request.description}</div>}
      <Form<FormValues>
        form={form}
        layout="vertical"
        onFinish={finish}
        initialValues={{ reason: '', limited: request.duration != null, duration_seconds: request.duration ?? 180 }}
      >
        {withDuration && (
          <Form.Item label="评分时长" required>
            <Space>
              <Form.Item name="limited" valuePropName="checked" noStyle>
                <Switch checkedChildren="限时" unCheckedChildren="不限时" />
              </Form.Item>
              {limited && (
                <Form.Item
                  name="duration_seconds"
                  noStyle
                  rules={[{ required: true, type: 'integer', min: 1, max: 86400, message: '时长为 1～86400 秒' }]}
                >
                  <InputNumber min={1} max={86400} precision={0} suffix="秒" className="duration-input" aria-label="评分时长（秒）" />
                </Form.Item>
              )}
            </Space>
            <Typography.Text type="secondary" className="field-help">
              {limited ? `从确认时起 ${seconds ? formatDuration(seconds) : '—'} 后截止` : '由主持人手动收评'}
            </Typography.Text>
          </Form.Item>
        )}
        <Form.Item
          label={request.reasonLabel}
          name="reason"
          rules={[
            ...(request.reasonRequired ? [{ required: true, whitespace: true, message: `请填写${request.reasonLabel}` }] : []),
            trimmedMax(500, '原因'),
          ]}
        >
          <Input.TextArea maxLength={500} autoSize={{ minRows: 2 }} placeholder={request.placeholder} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
