export type SetupTab = 'basic' | 'entries' | 'judges' | 'rule' | 'publish'

export const SETUP_STEPS: { key: SetupTab; title: string }[] = [
  { key: 'basic', title: '基本信息' },
  { key: 'entries', title: '参评对象' },
  { key: 'judges', title: '评委与身份码' },
  { key: 'rule', title: '评分规则' },
  { key: 'publish', title: '发布检查' },
]

export function isSetupTab(value: string | null): value is SetupTab {
  return SETUP_STEPS.some(s => s.key === value)
}

/** 发布检查问题的定位字段映射到设置页签，如 scoring_rule.criteria.0.step → 评分规则。 */
export function tabForField(field: string): SetupTab {
  if (field === 'entries' || field.startsWith('entries.')) return 'entries'
  if (field === 'judges' || field.startsWith('judges.')) return 'judges'
  if (field.startsWith('scoring_rule')) return 'rule'
  return 'basic'
}
