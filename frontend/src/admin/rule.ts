import { Big } from 'big.js'
import type { RuleInput } from '../api/types'
import { DECIMAL_PATTERN } from '../lib/decimal'

// 独立构造器，避免修改全局 Big 设置；规则数值最多 6 位小数，除以 100 精确。
const D = Big()
D.DP = 20

/** 权重以百分比录入；后端存 0～1 的小数且最多 6 位小数，故百分比最多 4 位小数。 */
const PERCENT_PATTERN = /^[0-9]{1,3}(\.[0-9]{1,4})?$/

export const MAX_CRITERIA = 20
export const MAX_MINIMUM_BALLOTS = 10000
export const TRIMMED_MEAN_FLOOR = 5

export interface CriterionForm {
  /** 内部维度标识，自动生成，不对用户展示；编辑时保留原值。 */
  criterion_id: string
  name: string
  maximum: string
  weightPercent: string
  step: string
}

export interface RuleForm {
  mode: 'single' | 'multi'
  criteria: CriterionForm[]
  algorithm: 'mean' | 'trimmed_mean'
  /** null 表示发布时按评委人数自动推导。 */
  minimumBallots: number | null
}

export interface RuleProblem {
  /** 与发布检查相同的点分隔定位，如 criteria.1.step。 */
  field: string
  message: string
}

export const DEFAULT_RULE: RuleInput = {
  mode: 'single',
  criteria: [{ criterion_id: 'total', name: '综合评分', maximum: '100', weight: '1', step: '0.1' }],
  algorithm: 'mean',
  minimum_ballots: null,
}

export function percentToWeight(percent: string): string {
  return new D(percent.trim()).div(100).toFixed()
}

export function weightToPercent(weight: string): string {
  return new D(weight).times(100).toFixed()
}

export function toRuleForm(rule: RuleInput | null | undefined): RuleForm {
  const source = rule ?? DEFAULT_RULE
  return {
    mode: source.mode ?? 'single',
    criteria: source.criteria.map(c => ({
      criterion_id: c.criterion_id,
      name: c.name,
      maximum: c.maximum ?? '100',
      weightPercent: weightToPercent(c.weight ?? '1'),
      step: c.step ?? '0.1',
    })),
    algorithm: source.algorithm ?? 'mean',
    minimumBallots: source.minimum_ballots ?? null,
  }
}

/** 新增维度的内部标识：c1、c2…，跳过已用值。 */
export function nextCriterionId(criteria: CriterionForm[]): string {
  const used = new Set(criteria.map(c => c.criterion_id))
  let n = criteria.length + 1
  while (used.has(`c${n}`)) n++
  return `c${n}`
}

/** 切换模式：单项只保留第一个维度且权重 100%；多维度至少两项。 */
export function switchMode(form: RuleForm, mode: RuleForm['mode']): RuleForm {
  if (mode === form.mode) return form
  if (mode === 'single') {
    const [first] = form.criteria
    return { ...form, mode, criteria: [{ ...first, weightPercent: '100' }] }
  }
  const criteria = [...form.criteria]
  while (criteria.length < 2) {
    criteria.push({ criterion_id: nextCriterionId(criteria), name: '', maximum: '100', weightPercent: '0', step: '0.1' })
  }
  return { ...form, mode, criteria }
}

function criterionProblems(c: CriterionForm, index: number, multi: boolean): RuleProblem[] {
  const at = (key: string, message: string) => ({ field: `criteria.${index}.${key}`, message })
  const problems: RuleProblem[] = []
  const name = c.name.trim()
  if (!name) problems.push(at('name', '请填写维度名称'))
  else if (name.length > 80) problems.push(at('name', '名称最多 80 字'))

  const maximum = c.maximum.trim()
  const step = c.step.trim()
  const maxOk = DECIMAL_PATTERN.test(maximum)
  const stepOk = DECIMAL_PATTERN.test(step)
  if (!maxOk) problems.push(at('maximum', '满分须为非负数字，最多 9 位整数、6 位小数'))
  else if (new D(maximum).lte(0)) problems.push(at('maximum', '满分须大于 0'))
  if (!stepOk) problems.push(at('step', '步长须为非负数字，最多 9 位整数、6 位小数'))
  else if (new D(step).lte(0)) problems.push(at('step', '步长须大于 0'))
  if (maxOk && stepOk && new D(maximum).gt(0) && new D(step).gt(0)) {
    if (new D(step).gt(maximum)) problems.push(at('step', '步长不能大于满分'))
    else if (!new D(maximum).mod(step).eq(0)) problems.push(at('step', '满分须为步长的整数倍'))
  }

  if (multi) {
    const percent = c.weightPercent.trim()
    if (!PERCENT_PATTERN.test(percent) || new D(percent).gt(100)) {
      problems.push(at('weight', '权重须为 0～100 的百分比，最多 4 位小数'))
    }
  }
  return problems
}

/**
 * 与后端草稿保存时的规则校验一致（RuleInput + 评分核心）：模式与维度数、满分/步长、权重合计 100%、
 * 显式 K 的范围及去极值下限。K 与评委人数 N 的关系在发布检查中判断，见 {@link rosterProblems}。
 */
export function ruleProblems(form: RuleForm): RuleProblem[] {
  const multi = form.mode === 'multi'
  const problems: RuleProblem[] = []
  if (!multi && form.criteria.length !== 1) problems.push({ field: 'criteria', message: '单项评分只能有一个维度' })
  if (multi && form.criteria.length < 2) problems.push({ field: 'criteria', message: '多维度评分至少需要两个维度' })
  if (form.criteria.length > MAX_CRITERIA) problems.push({ field: 'criteria', message: `最多 ${MAX_CRITERIA} 个维度` })
  form.criteria.forEach((c, i) => problems.push(...criterionProblems(c, i, multi)))

  if (multi && !problems.some(p => p.field.endsWith('.weight'))) {
    const sum = form.criteria.reduce((total, c) => total.plus(c.weightPercent.trim()), new D(0))
    if (!sum.eq(100)) problems.push({ field: 'criteria', message: `权重合计须为 100%，当前为 ${sum.toFixed()}%` })
  }

  const k = form.minimumBallots
  if (k !== null) {
    if (!Number.isInteger(k) || k < 1 || k > MAX_MINIMUM_BALLOTS) {
      problems.push({ field: 'minimum_ballots', message: `最低有效份数须为 1～${MAX_MINIMUM_BALLOTS} 的整数` })
    } else if (form.algorithm === 'trimmed_mean' && k < TRIMMED_MEAN_FLOOR) {
      problems.push({ field: 'minimum_ballots', message: `去最高最低分时最低有效份数不能少于 ${TRIMMED_MEAN_FLOOR}` })
    }
  }
  return problems
}

/** 结合当前评委人数的提示（发布阻塞项），草稿阶段仅作提醒，以发布检查结果为准。 */
export function rosterProblems(form: RuleForm, judgeCount: number): RuleProblem[] {
  const problems: RuleProblem[] = []
  if (judgeCount === 0) return problems
  if (form.algorithm === 'trimmed_mean' && judgeCount < TRIMMED_MEAN_FLOOR) {
    problems.push({ field: 'algorithm', message: `去最高最低分需要至少 ${TRIMMED_MEAN_FLOOR} 位评委，当前 ${judgeCount} 位` })
  }
  if (form.minimumBallots !== null && form.minimumBallots > judgeCount) {
    problems.push({ field: 'minimum_ballots', message: `最低有效份数不能超过评委人数 ${judgeCount}` })
  }
  return problems
}

/** 与评分核心相同：平均分 max(1, ceil(0.8N))，去极值 max(5, ceil(0.8N))；无法满足时返回 null。 */
export function defaultMinimumBallots(judgeCount: number, algorithm: RuleForm['algorithm']): number | null {
  if (judgeCount < 1) return null
  const floor = algorithm === 'trimmed_mean' ? TRIMMED_MEAN_FLOOR : 1
  const minimum = Math.max(floor, Math.floor((4 * judgeCount + 4) / 5))
  return minimum > judgeCount ? null : minimum
}

export function fromRuleForm(form: RuleForm): RuleInput {
  const multi = form.mode === 'multi'
  return {
    mode: form.mode,
    criteria: form.criteria.map(c => ({
      criterion_id: c.criterion_id,
      name: c.name.trim(),
      maximum: c.maximum.trim(),
      weight: multi ? percentToWeight(c.weightPercent) : '1',
      step: c.step.trim(),
    })),
    algorithm: form.algorithm,
    minimum_ballots: form.minimumBallots,
  }
}
