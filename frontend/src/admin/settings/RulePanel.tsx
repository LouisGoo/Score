import { useMemo, useState, type ReactNode } from 'react'
import { Alert, App, Button, Descriptions, Empty, Flex, Form, Input, InputNumber, Radio, Space, Table, Typography } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { useMutation } from '@tanstack/react-query'
import { Big } from 'big.js'
import { adminEvents } from '../../api/admin'
import type { EventInfo, PublicationInfo } from '../../api/types'
import {
  DEFAULT_RULE,
  MAX_CRITERIA,
  MAX_MINIMUM_BALLOTS,
  defaultMinimumBallots,
  fromRuleForm,
  nextCriterionId,
  rosterProblems,
  ruleProblems,
  switchMode,
  toRuleForm,
  weightToPercent,
  type CriterionForm,
  type RuleForm,
} from '../rule'
import { useReportError } from '../session'
import { useRefreshEvent } from './data'

const algorithmText = {
  mean: '平均分：全部有效评分的平均值',
  trimmed_mean: '去最高最低后平均：去掉一个最高分和一个最低分，至少 5 位评委',
}

interface Props {
  event: EventInfo
  editable: boolean
  judgeCount: number
  publication?: PublicationInfo
}

export function RulePanel({ event, editable, judgeCount, publication }: Props) {
  if (!editable) return <FrozenRule event={event} publication={publication} />
  // 服务端规则变化（保存或刷新）时以新值重建编辑状态。
  return <RuleEditor key={JSON.stringify(event.scoring_rule)} event={event} judgeCount={judgeCount} />
}

function RuleEditor({ event, judgeCount }: { event: EventInfo; judgeCount: number }) {
  const [form, setForm] = useState<RuleForm | null>(event.scoring_rule ? toRuleForm(event.scoring_rule) : null)
  const [touched, setTouched] = useState(false)
  const { message } = App.useApp()
  const report = useReportError()
  const refresh = useRefreshEvent(event.id)

  const problems = useMemo(() => (form ? ruleProblems(form) : []), [form])
  const warnings = useMemo(() => (form ? rosterProblems(form, judgeCount) : []), [form, judgeCount])
  const fieldError = (field: string) => problems.filter(p => p.field === field).map(p => p.message)
  const dirty = form !== null && JSON.stringify(form) !== JSON.stringify(event.scoring_rule ? toRuleForm(event.scoring_rule) : null)

  const save = useMutation({
    mutationFn: (rule: RuleForm) => adminEvents.patch(event.id, { scoring_rule: fromRuleForm(rule) }),
    onSuccess: () => {
      message.success('评分规则已保存')
      void refresh()
    },
    onError: error => {
      if (report(error, '保存失败').action !== 'fix') void refresh()
    },
  })

  if (!form) {
    return (
      <Empty description="尚未配置评分规则">
        <Button type="primary" onClick={() => setForm(toRuleForm(DEFAULT_RULE))}>使用默认规则开始</Button>
      </Empty>
    )
  }

  const update = (next: RuleForm) => {
    setTouched(true)
    setForm(next)
  }
  const updateCriterion = (index: number, patch: Partial<CriterionForm>) =>
    update({ ...form, criteria: form.criteria.map((c, i) => (i === index ? { ...c, ...patch } : c)) })
  const multi = form.mode === 'multi'
  const derived = defaultMinimumBallots(judgeCount, form.algorithm)
  const weightSum = multi ? safeSum(form.criteria.map(c => c.weightPercent)) : null
  const show = (field: string) => (touched ? fieldError(field) : [])
  const status = (field: string) => (show(field).length ? 'error' : undefined)

  return (
    <Form layout="vertical" disabled={save.isPending}>
      <Form.Item label="评分模式">
        <Radio.Group
          value={form.mode}
          onChange={e => update(switchMode(form, e.target.value))}
          options={[
            { value: 'single', label: '单项总分' },
            { value: 'multi', label: '多维度加权' },
          ]}
          optionType="button"
        />
      </Form.Item>

      <Form.Item
        label={multi ? '评分维度（个人总分 = 100 × Σ 得分 / 满分 × 权重）' : '评分项'}
        validateStatus={show('criteria').length ? 'error' : undefined}
        help={show('criteria').join('；') || undefined}
      >
        <Table<CriterionForm>
          rowKey="criterion_id"
          dataSource={form.criteria}
          pagination={false}
          size="small"
          columns={[
            {
              title: '名称',
              render: (_, c, i) => (
                <FieldCell errors={show(`criteria.${i}.name`)}>
                  <Input value={c.name} maxLength={80} status={status(`criteria.${i}.name`)} aria-label={`维度 ${i + 1} 名称`} onChange={e => updateCriterion(i, { name: e.target.value })} />
                </FieldCell>
              ),
            },
            {
              title: '满分',
              width: 130,
              render: (_, c, i) => (
                <FieldCell errors={show(`criteria.${i}.maximum`)}>
                  <Input value={c.maximum} inputMode="decimal" status={status(`criteria.${i}.maximum`)} aria-label={`维度 ${i + 1} 满分`} onChange={e => updateCriterion(i, { maximum: e.target.value })} />
                </FieldCell>
              ),
            },
            {
              title: '输入步长',
              width: 130,
              render: (_, c, i) => (
                <FieldCell errors={show(`criteria.${i}.step`)}>
                  <Input value={c.step} inputMode="decimal" status={status(`criteria.${i}.step`)} aria-label={`维度 ${i + 1} 步长`} onChange={e => updateCriterion(i, { step: e.target.value })} />
                </FieldCell>
              ),
            },
            ...(multi
              ? [
                  {
                    title: '权重',
                    width: 130,
                    render: (_: unknown, c: CriterionForm, i: number) => (
                      <FieldCell errors={show(`criteria.${i}.weight`)}>
                        <Input value={c.weightPercent} inputMode="decimal" suffix="%" status={status(`criteria.${i}.weight`)} aria-label={`维度 ${i + 1} 权重`} onChange={e => updateCriterion(i, { weightPercent: e.target.value })} />
                      </FieldCell>
                    ),
                  },
                  {
                    title: '',
                    width: 48,
                    render: (_: unknown, __: CriterionForm, i: number) => (
                      <Button
                        type="text"
                        icon={<DeleteOutlined />}
                        aria-label={`删除维度 ${i + 1}`}
                        disabled={form.criteria.length <= 2}
                        onClick={() => update({ ...form, criteria: form.criteria.filter((_c, j) => j !== i) })}
                      />
                    ),
                  },
                ]
              : []),
          ]}
        />
        {multi && (
          <Flex justify="space-between" align="center" className="criteria-footer">
            <Button
              icon={<PlusOutlined />}
              disabled={form.criteria.length >= MAX_CRITERIA}
              onClick={() =>
                update({
                  ...form,
                  criteria: [...form.criteria, { criterion_id: nextCriterionId(form.criteria), name: '', maximum: '100', weightPercent: '0', step: '0.1' }],
                })
              }
            >
              添加维度
            </Button>
            <Typography.Text type={weightSum === '100' ? 'success' : 'warning'}>权重合计 {weightSum ?? '—'}%</Typography.Text>
          </Flex>
        )}
      </Form.Item>

      <Form.Item label="汇总算法" extra={algorithmText[form.algorithm]}>
        <Radio.Group
          value={form.algorithm}
          onChange={e => update({ ...form, algorithm: e.target.value })}
          options={[
            { value: 'mean', label: '平均分' },
            { value: 'trimmed_mean', label: '去最高最低后平均' },
          ]}
          optionType="button"
        />
      </Form.Item>

      <Form.Item
        label="最低有效份数 K"
        validateStatus={show('minimum_ballots').length ? 'error' : undefined}
        help={show('minimum_ballots').join('；') || undefined}
        extra="收评时有效评分少于 K 份不能公布成绩，可重开补评或标记无结果。"
      >
        <Space wrap>
          <Radio.Group
            value={form.minimumBallots === null ? 'auto' : 'fixed'}
            onChange={e => update({ ...form, minimumBallots: e.target.value === 'auto' ? null : (derived ?? Math.min(Math.max(judgeCount, 1), MAX_MINIMUM_BALLOTS)) })}
            options={[
              { value: 'auto', label: `自动（评委人数的 80% 向上取整${form.algorithm === 'trimmed_mean' ? '，至少 5' : ''}）` },
              { value: 'fixed', label: '指定' },
            ]}
          />
          {form.minimumBallots !== null && (
            <InputNumber
              min={1}
              max={MAX_MINIMUM_BALLOTS}
              precision={0}
              value={form.minimumBallots}
              aria-label="最低有效份数"
              onChange={value => update({ ...form, minimumBallots: typeof value === 'number' ? value : 1 })}
              suffix="份"
            />
          )}
          {form.minimumBallots === null && judgeCount > 0 && (
            <Typography.Text type="secondary">按当前 {judgeCount} 位评委：{derived === null ? '人数不足' : `K = ${derived}`}</Typography.Text>
          )}
        </Space>
      </Form.Item>

      {warnings.length > 0 && (
        <Alert type="warning" showIcon className="form-alert" title="按当前评委名单将无法发布" description={warnings.map(w => <div key={w.field}>{w.message}</div>)} />
      )}

      <Space>
        <Button
          type="primary"
          loading={save.isPending}
          disabled={!dirty}
          onClick={() => {
            setTouched(true)
            if (problems.length === 0) save.mutate(form)
          }}
        >
          保存评分规则
        </Button>
        <Button disabled={!dirty} onClick={() => { setForm(event.scoring_rule ? toRuleForm(event.scoring_rule) : null); setTouched(false) }}>
          还原
        </Button>
        {touched && problems.length > 0 && <Typography.Text type="danger">请先修正 {problems.length} 处问题</Typography.Text>}
      </Space>
    </Form>
  )
}

function FieldCell({ errors, children }: { errors: string[]; children: ReactNode }) {
  return (
    <>
      {children}
      {errors.length > 0 && <Typography.Text type="danger" className="cell-error">{errors.join('；')}</Typography.Text>}
    </>
  )
}

function safeSum(values: string[]): string | null {
  try {
    return values.reduce((sum, v) => sum.plus(v.trim() || '0'), new Big(0)).toFixed()
  } catch {
    return null
  }
}

/** 已发布活动：展示发布时冻结的规则，含实际 K 与应交份数 N。 */
function FrozenRule({ event, publication }: { event: EventInfo; publication?: PublicationInfo }) {
  const rule = publication?.snapshot.scoring_rule ?? event.scoring_rule
  if (!rule) return <Empty description="未配置评分规则" />
  const frozen = publication?.snapshot.scoring_rule
  return (
    <>
      <Descriptions
        column={{ xs: 1, md: 2 }}
        bordered
        size="small"
        items={[
          { key: 'mode', label: '评分模式', children: rule.mode === 'multi' ? '多维度加权' : '单项总分' },
          { key: 'algorithm', label: '汇总算法', children: rule.algorithm === 'trimmed_mean' ? '去最高最低后平均' : '平均分' },
          { key: 'k', label: '最低有效份数 K', children: frozen ? frozen.minimum_ballots : (rule.minimum_ballots ?? '发布时推导') },
          { key: 'n', label: '应交份数 N', children: frozen ? frozen.expected_count : '—' },
        ]}
      />
      <Table
        className="frozen-criteria"
        rowKey="criterion_id"
        size="small"
        pagination={false}
        dataSource={rule.criteria}
        columns={[
          { title: '维度', dataIndex: 'name' },
          { title: '满分', dataIndex: 'maximum', width: 120 },
          { title: '输入步长', dataIndex: 'step', width: 120 },
          { title: '权重', dataIndex: 'weight', width: 120, render: (w: string) => `${weightToPercent(w ?? '1')}%` },
        ]}
      />
    </>
  )
}
