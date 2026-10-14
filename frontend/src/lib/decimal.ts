import { Big } from 'big.js'

/** 与后端 DecimalString 相同：最多 9 位整数、6 位小数的非负十进制文本。 */
export const DECIMAL_PATTERN = /^[0-9]{1,9}(\.[0-9]{1,6})?$/

export interface CriterionRule {
  criterion_id: string
  maximum: string
  weight: string
  step: string
}

// 独立构造器，不改动全局 Big 设置；截断除法后再统一 ROUND_HALF_UP。
const Exact = Big()
Exact.DP = 60
Exact.RM = Big.roundDown

/** 校验单项分数；空值表示未填，返回 null 以外的文本为错误原因。 */
export function scoreError(value: string, criterion: CriterionRule): string | null {
  const text = value.trim()
  if (text === '') return '请填写分数'
  if (!DECIMAL_PATTERN.test(text)) return '请输入非负数字，最多 6 位小数'
  const score = new Exact(text)
  if (score.gt(criterion.maximum)) return `不能超过满分 ${criterion.maximum}`
  if (!score.mod(criterion.step).eq(0)) return `须为 ${criterion.step} 的整数倍`
  return null
}

/**
 * 个人百分制总分预览：100 × Σ(x / M × w)，两位小数 ROUND_HALF_UP。
 * 与后端相同先通分：分子精确累加，最后只做一次除法，避免中间舍入改变边界结果。
 * 有维度未填或不合法时返回 null；仅供展示，权威值以提交回执为准。
 */
export function personalTotal(criteria: CriterionRule[], scores: Record<string, string>): string | null {
  if (criteria.length === 0) return null
  if (criteria.some(c => scoreError(scores[c.criterion_id] ?? '', c) !== null)) return null
  const maxima = criteria.map(c => new Exact(c.maximum))
  const denominator = maxima.reduce((product, m) => product.times(m), new Exact(1))
  const numerator = criteria.reduce((sum, c, i) => {
    const others = maxima.reduce((product, m, j) => (j === i ? product : product.times(m)), new Exact(1))
    return sum.plus(new Exact(scores[c.criterion_id].trim()).times(c.weight).times(100).times(others))
  }, new Exact(0))
  return numerator.div(denominator).round(2, Big.roundHalfUp).toFixed(2)
}
