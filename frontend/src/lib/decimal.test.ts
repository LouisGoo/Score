import { describe, expect, it } from 'vitest'
import { personalTotal, scoreError, type CriterionRule } from './decimal'

const c = (criterion_id: string, maximum: string, weight: string, step: string): CriterionRule => ({
  criterion_id,
  maximum,
  weight,
  step,
})

describe('personalTotal', () => {
  // 期望值由后端 score_api.scoring.personal_total 计算后按 ROUND_HALF_UP 保留两位得到。
  it.each([
    [[c('content', '100', '0.5', '0.1'), c('performance', '10', '0.3', '0.1'), c('innovation', '20', '0.2', '0.1')], { content: '90', performance: '8', innovation: '18' }, '87.00'],
    [[c('a', '3', '1', '1')], { a: '1' }, '33.33'],
    [[c('a', '3', '1', '1')], { a: '2' }, '66.67'],
    [[c('a', '200', '1', '0.01')], { a: '2.01' }, '1.01'],
    [[c('a', '7', '0.333333', '1'), c('b', '9', '0.666667', '1')], { a: '5', b: '4' }, '53.44'],
    [[c('a', '100', '1', '0.1')], { a: '0' }, '0.00'],
  ])('matches backend for %j %j', (criteria, scores, expected) => {
    expect(personalTotal(criteria, scores)).toBe(expected)
  })

  it('accepts equivalent decimal text and surrounding whitespace', () => {
    expect(personalTotal([c('a', '100', '1', '0.1')], { a: ' 90.0 ' })).toBe('90.00')
  })

  it('returns null while any criterion is empty or invalid', () => {
    const rule = [c('a', '10', '0.5', '1'), c('b', '10', '0.5', '1')]
    expect(personalTotal(rule, { a: '5' })).toBeNull()
    expect(personalTotal(rule, { a: '5', b: '' })).toBeNull()
    expect(personalTotal(rule, { a: '5', b: '11' })).toBeNull()
    expect(personalTotal([], {})).toBeNull()
  })
})

describe('scoreError', () => {
  const rule = c('a', '10', '1', '0.5')

  it('treats zero as valid and empty as missing', () => {
    expect(scoreError('0', rule)).toBeNull()
    expect(scoreError('', rule)).toBe('请填写分数')
    expect(scoreError('   ', rule)).toBe('请填写分数')
  })

  it('rejects formats the backend rejects', () => {
    for (const value of ['-1', '1e2', '1.', '.5', 'NaN', 'Infinity', '1.1234567', '1234567890']) {
      expect(scoreError(value, rule)).not.toBeNull()
    }
  })

  it('checks maximum and step from zero', () => {
    expect(scoreError('10', rule)).toBeNull()
    expect(scoreError('10.5', rule)).toContain('满分')
    expect(scoreError('2.5', rule)).toBeNull()
    expect(scoreError('2.3', rule)).toContain('0.5')
  })
})
