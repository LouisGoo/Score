import { describe, expect, it } from 'vitest'
import { partialTotal, personalTotal, scoreError, type CriterionRule } from './decimal'

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
    expect(partialTotal(criteria, scores)).toMatchObject({ total: expected, complete: true, errors: {} })
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

describe('partialTotal', () => {
  const rule = [c('a', '30', '0.3', '0.1'), c('b', '30', '0.3', '0.1'), c('c', '20', '0.2', '0.1'), c('d', '20', '0.2', '0.1')]

  it('accumulates each item and recalculates edits and deletions', () => {
    const scores: Record<string, string> = {}
    expect(partialTotal(rule, scores)).toEqual({ total: '0.00', validCount: 0, totalCount: 4, errors: {}, complete: false })
    for (const [id, value, expected, count] of [
      ['a', '27', '27.00', 1], ['b', '28', '55.00', 2], ['c', '18', '73.00', 3],
      ['d', '19', '92.00', 4], ['a', '29', '94.00', 4], ['d', '', '75.00', 3],
    ] as const) {
      scores[id] = value
      expect(partialTotal(rule, scores)).toMatchObject({ total: expected, validCount: count, complete: count === 4 })
    }
    expect(scores.d).toBe('')
    expect(personalTotal(rule, scores)).toBeNull()
  })

  it('keeps original weights, counts zero, ignores blank and unrelated values without changing the draft', () => {
    const criteria = [c('a', '100', '0.3', '1'), c('b', '10', '0.3', '1'), c('c', '20', '0.4', '1')]
    const scores = Object.freeze({ a: ' 80 ', b: '0', c: '  ', unknown: '99' })
    expect(partialTotal(criteria, scores)).toEqual({ total: '24.00', validCount: 2, totalCount: 3, errors: {}, complete: false })
    expect(partialTotal([], {})).toEqual({ total: '0.00', validCount: 0, totalCount: 0, errors: {}, complete: false })
    expect(partialTotal([c('a', '100', '1', '1')], { a: '0' })).toMatchObject({ total: '0.00', validCount: 1, complete: true })
  })

  it.each(['-1', '1e2', '1.', '.5', 'NaN', 'Infinity', '1.1234567', '1234567890', '31', '1.05'])('excludes invalid input %s and reports the error', value => {
    const result = partialTotal(rule, { a: value, b: '28' })
    expect(result).toMatchObject({ total: '28.00', validCount: 1, complete: false })
    expect(result.errors).toEqual({ a: scoreError(value, rule[0]) })
  })

  it('rounds only after summing exact contributions, including half-up boundaries', () => {
    const criteria = [c('a', '3', '0.3', '0.0001'), c('b', '7', '0.7', '0.0001'), c('c', '100', '0', '1')]
    expect(partialTotal(criteria, { a: '0.0004', b: '0.0004' }).total).toBe('0.01')
    expect(partialTotal(criteria, { a: '0.0002', b: '0.0003' }).total).toBe('0.01')
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
