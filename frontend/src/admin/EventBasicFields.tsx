import { Col, DatePicker, Divider, Form, Input, InputNumber, Radio, Row, Space, Switch, Typography } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import type { EventCreate, EventInfo, EventPatch } from '../api/types'
import { formatDuration } from './format'
import { trimmedMax } from './settings/fields'

export interface BasicValues {
  title: string
  organization: string
  description: string
  planned_at: Dayjs | null
  limited: boolean
  duration_seconds: number | null
  allow_revisions: boolean
  screen_title: string
  screen_theme: 'light' | 'dark'
  show_public_qr: boolean
  leaderboard_limit: number
}

type BasicPayload = Omit<EventCreate, 'scoring_rule'>

export function toBasicValues(event?: EventInfo): BasicValues {
  return {
    title: event?.title ?? '',
    organization: event?.organization ?? '',
    description: event?.description ?? '',
    planned_at: event?.planned_at ? dayjs(event.planned_at) : null,
    limited: event ? event.duration_seconds != null : true,
    duration_seconds: event ? (event.duration_seconds ?? null) : 180,
    allow_revisions: event?.allow_revisions ?? true,
    screen_title: event?.screen_title ?? '',
    screen_theme: event?.screen_theme ?? 'light',
    show_public_qr: event?.show_public_qr ?? true,
    leaderboard_limit: event?.leaderboard_limit ?? 10,
  }
}

/** 文本与后端一致去首尾空白；计划时间带时区偏移发送，服务端存 UTC。 */
export function basicPayload(values: BasicValues): BasicPayload {
  return {
    title: values.title.trim(),
    organization: values.organization.trim(),
    description: values.description.trim(),
    planned_at: values.planned_at ? values.planned_at.second(0).millisecond(0).format() : null,
    duration_seconds: values.limited ? values.duration_seconds : null,
    allow_revisions: values.allow_revisions,
    screen_title: values.screen_title.trim(),
    screen_theme: values.screen_theme,
    show_public_qr: values.show_public_qr,
    leaderboard_limit: values.leaderboard_limit,
  }
}

function sameTime(a: string | null | undefined, b: string | null | undefined) {
  if (!a || !b) return !a && !b
  return dayjs(a).valueOf() === dayjs(b).valueOf()
}

/** 只提交有变化的字段；草稿接口无版本校验，减少覆盖他人同时修改的其他字段。 */
export function basicPatch(event: EventInfo, values: BasicValues): EventPatch {
  const next = basicPayload(values)
  const patch: EventPatch = {}
  const keys = Object.keys(next) as (keyof BasicPayload)[]
  for (const key of keys) {
    const changed = key === 'planned_at' ? !sameTime(event.planned_at, next.planned_at) : (event[key] ?? null) !== (next[key] ?? null)
    if (changed) Object.assign(patch, { [key]: next[key] })
  }
  return patch
}

/** 基本信息、过程规则与大屏设置字段；须放在 Form<BasicValues> 内。 */
export function BasicFields() {
  const limited = Form.useWatch<boolean>('limited')
  const duration = Form.useWatch<number | null>('duration_seconds')
  return (
    <>
      <Row gutter={24}>
        <Col xs={24} md={12}>
          <Form.Item
            label="活动名称"
            name="title"
            rules={[{ required: true, whitespace: true, message: '请填写活动名称' }, trimmedMax(80, '活动名称')]}
          >
            <Input maxLength={80} showCount placeholder="如：2026 年度项目评审" />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item label="组织名称" name="organization" rules={[trimmedMax(120, '组织名称')]}>
            <Input maxLength={120} />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item label="计划时间" name="planned_at">
            <DatePicker showTime={{ format: 'HH:mm' }} format="YYYY-MM-DD HH:mm" className="full-width" />
          </Form.Item>
        </Col>
        <Col xs={24}>
          <Form.Item label="简介" name="description" rules={[trimmedMax(2000, '简介')]}>
            <Input.TextArea maxLength={2000} showCount autoSize={{ minRows: 2, maxRows: 6 }} />
          </Form.Item>
        </Col>
      </Row>

      <Divider titlePlacement="start">过程规则</Divider>
      <Row gutter={24}>
        <Col xs={24} md={12}>
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
                  <InputNumber min={1} max={86400} precision={0} suffix="秒" className="duration-input" />
                </Form.Item>
              )}
            </Space>
            <Typography.Text type="secondary" className="field-help">
              {limited ? `每个对象开评后 ${duration ? formatDuration(duration) : '—'} 自动截止，可暂停` : '由主持人手动收评'}
            </Typography.Text>
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item label="开放期允许改分" name="allow_revisions" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Col>
      </Row>

      <Divider titlePlacement="start">大屏设置</Divider>
      <Row gutter={24}>
        <Col xs={24} md={12}>
          <Form.Item label="大屏标题" name="screen_title" rules={[trimmedMax(80, '大屏标题')]} extra="留空时使用活动名称">
            <Input maxLength={80} />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item label="主题" name="screen_theme">
            <Radio.Group options={[{ value: 'light', label: '浅色' }, { value: 'dark', label: '深色' }]} optionType="button" />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item label="显示公共二维码" name="show_public_qr" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item
            label="排行榜显示数量"
            name="leaderboard_limit"
            rules={[{ required: true, type: 'integer', min: 1, max: 10000, message: '数量为 1～10000' }]}
          >
            <InputNumber min={1} max={10000} precision={0} />
          </Form.Item>
        </Col>
      </Row>
    </>
  )
}