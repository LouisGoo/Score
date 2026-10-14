import type { FormRule as Rule } from 'antd'

/** 与后端一致：先去首尾空白再计长度。 */
export function trimmedMax(max: number, label: string): Rule {
  return {
    validator: (_, value?: string) =>
      (value ?? '').trim().length <= max ? Promise.resolve() : Promise.reject(new Error(`${label}最多 ${max} 字`)),
  }
}

/** 编号：去空白后 1～32 字的字符串，活动内唯一（服务端以唯一约束兜底）。 */
export function numberRules(kind: string): Rule[] {
  return [{ required: true, whitespace: true, message: `请填写${kind}编号` }, trimmedMax(32, '编号')]
}

/**
 * 建议下一个编号：已有编号均为等宽数字时按最大值加一并补零（001→002），否则按数量补三位。
 * 仅作输入默认值，可修改。
 */
export function nextNumber(existing: string[]): string {
  const numeric = existing.filter(n => /^[0-9]+$/.test(n))
  const width = numeric.length === existing.length && numeric.length ? Math.max(...numeric.map(n => n.length)) : 3
  const used = new Set(existing)
  let next = numeric.length ? Math.max(...numeric.map(Number)) + 1 : existing.length + 1
  while (used.has(String(next).padStart(width, '0'))) next++
  return String(next).padStart(width, '0')
}
