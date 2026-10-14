import dayjs from 'dayjs'
import { describe, expect, it } from 'vitest'
import type { EventInfo } from '../api/types'
import { basicPatch, toBasicValues } from './EventBasicFields'
import {
  DEFAULT_RULE,
  defaultMinimumBallots,
  fromRuleForm,
  percentToWeight,
  rosterProblems,
  ruleProblems,
  switchMode,
  toRuleForm,
  weightToPercent,
  type RuleForm,
} from './rule'
import { safeNext } from './session'
import { credentialError } from './settings/JudgesPanel'
import { nextNumber } from './settings/fields'
import { tabForField } from './settings/steps'

const multi = (weights: string[], extra: Partial<RuleForm> = {}): RuleForm => ({
  mode: 'multi',
  criteria: weights.map((w, i) => ({ criterion_id: `c${i + 1}`, name: `维度${i + 1}`, maximum: '100', weightPercent: w, step: '0.1' })),
  algorithm: 'mean',
  minimumBallots: null,
  ...extra,
})

const trimmed = (k: number | null): RuleForm => ({ ...toRuleForm(DEFAULT_RULE), algorithm: 'trimmed_mean', minimumBallots: k })

describe('rule form', () => {
  it('converts percentages to exact decimal weights and back', () => {
    expect(percentToWeight('50')).toBe('0.5')
    expect(percentToWeight('33.3333')).toBe('0.333333')
    expect(percentToWeight('100')).toBe('1')
    expect(weightToPercent('0.125')).toBe('12.5')
    expect(weightToPercent('1')).toBe('100')
  })

  it('round-trips the backend rule and fixes single-mode weight to 1', () => {
    expect(fromRuleForm(toRuleForm(DEFAULT_RULE))).toEqual(DEFAULT_RULE)
    const rule = fromRuleForm(multi(['50', '30', '20']))
    expect(rule.criteria.map(c => c.weight)).toEqual(['0.5', '0.3', '0.2'])
    expect(fromRuleForm(switchMode(multi(['60', '40']), 'single')).criteria).toEqual([
      { criterion_id: 'c1', name: '维度1', maximum: '100', weight: '1', step: '0.1' },
    ])
  })

  it('accepts a valid rule', () => {
    expect(ruleProblems(toRuleForm(DEFAULT_RULE))).toEqual([])
    expect(ruleProblems(multi(['33.3333', '33.3333', '33.3334']))).toEqual([])
  })

  it('requires weights to sum exactly to 100%', () => {
    expect(ruleProblems(multi(['50', '40']))).toEqual([{ field: 'criteria', message: '权重合计须为 100%，当前为 90%' }])
    expect(ruleProblems(multi(['33.3333', '33.3333', '33.3333']))[0].field).toBe('criteria')
  })

  it('locates criterion problems with the same field paths as publish-check', () => {
    const form = multi(['50', '50'])
    form.criteria[1] = { ...form.criteria[1], name: ' ', maximum: '10', step: '3', weightPercent: '50.00001' }
    expect(ruleProblems(form).map(p => p.field)).toEqual(['criteria.1.name', 'criteria.1.step', 'criteria.1.weight'])
    form.criteria[1] = { ...form.criteria[1], name: 'x', step: '20', weightPercent: '50' }
    expect(ruleProblems(form)).toEqual([{ field: 'criteria.1.step', message: '步长不能大于满分' }])
    form.criteria[1] = { ...form.criteria[1], maximum: '1e3', step: '0' }
    expect(ruleProblems(form).map(p => p.field)).toEqual(['criteria.1.maximum', 'criteria.1.step'])
  })

  it('checks criterion count per mode', () => {
    expect(ruleProblems({ ...multi(['100']), mode: 'multi' })[0].message).toBe('多维度评分至少需要两个维度')
    expect(ruleProblems({ ...multi(['50', '50']), mode: 'single' })[0].message).toBe('单项评分只能有一个维度')
    expect(switchMode(toRuleForm(DEFAULT_RULE), 'multi').criteria).toHaveLength(2)
  })

  it('applies the K floor at save time and K≤N only against the roster', () => {
    expect(ruleProblems(trimmed(4)).map(p => p.field)).toEqual(['minimum_ballots'])
    expect(ruleProblems(trimmed(5))).toEqual([])
    expect(rosterProblems(trimmed(null), 4).map(p => p.field)).toEqual(['algorithm'])
    expect(rosterProblems(trimmed(6), 5).map(p => p.field)).toEqual(['minimum_ballots'])
    expect(rosterProblems(trimmed(null), 0)).toEqual([])
  })

  it('derives the default K exactly like the scoring core', () => {
    expect([1, 2, 3, 4, 5, 6, 10, 50].map(n => defaultMinimumBallots(n, 'mean'))).toEqual([1, 2, 3, 4, 4, 5, 8, 40])
    expect([4, 5, 6, 7].map(n => defaultMinimumBallots(n, 'trimmed_mean'))).toEqual([null, 5, 5, 6])
    expect(defaultMinimumBallots(0, 'mean')).toBeNull()
  })
})

describe('form helpers', () => {
  it('validates credentials with the backend normalization rules', () => {
    expect(credentialError(' abcd1234 ')).toBeNull()
    expect(credentialError('abcdefgh')).toBe('身份码须同时包含字母和数字')
    expect(credentialError('12345678')).toBe('身份码须同时包含字母和数字')
    expect(credentialError('abc123')).toBe('身份码为 8～32 位英文字母或数字')
    expect(credentialError('ａｂｃｄ1234')).toBe('身份码为 8～32 位英文字母或数字')
  })

  it('suggests the next roster number preserving leading zeros', () => {
    expect(nextNumber([])).toBe('001')
    expect(nextNumber(['001', '002'])).toBe('003')
    expect(nextNumber(['1', '9'])).toBe('10')
    expect(nextNumber(['A1', 'B2'])).toBe('003')
  })

  it('only redirects to in-app admin paths after login', () => {
    expect(safeNext('/admin/events/e1/settings?tab=rule')).toBe('/admin/events/e1/settings?tab=rule')
    expect(safeNext('https://evil.example/admin/')).toBe('/admin/events')
    expect(safeNext('//evil.example')).toBe('/admin/events')
    expect(safeNext('/admin/login?next=x')).toBe('/admin/events')
    expect(safeNext(null)).toBe('/admin/events')
  })

  it('maps publish-check fields to settings tabs', () => {
    expect(tabForField('entries')).toBe('entries')
    expect(tabForField('judges')).toBe('judges')
    expect(tabForField('scoring_rule.criteria.0.step')).toBe('rule')
    expect(tabForField('scoring_rule')).toBe('rule')
  })

  it('patches only changed basic fields and compares times by instant', () => {
    const event = {
      id: 'e1',
      title: '项目评审',
      description: '',
      organization: '研发部',
      planned_at: '2026-10-12T06:00:00Z',
      duration_seconds: 180,
      allow_revisions: true,
      screen_title: '',
      screen_theme: 'light',
      show_public_qr: true,
      leaderboard_limit: 10,
    } as EventInfo
    const values = toBasicValues(event)
    expect(basicPatch(event, values)).toEqual({})
    expect(basicPatch(event, { ...values, title: ' 新标题 ', limited: false })).toEqual({ title: '新标题', duration_seconds: null })
    const planned = basicPatch(event, { ...values, planned_at: dayjs('2026-10-12T07:30:00Z') })
    expect(Object.keys(planned)).toEqual(['planned_at'])
    expect(dayjs(planned.planned_at!).toISOString()).toBe('2026-10-12T07:30:00.000Z')
    expect(basicPatch(event, { ...values, planned_at: null })).toEqual({ planned_at: null })
  })
})
