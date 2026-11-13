import { expect, it } from 'vitest'
import type { Service } from '../catalogue/types.ts'
import { parseSelection, selectionQuery, totalMinutes } from './selection.ts'

function service(slug: string, minutes: number): Service {
  return {
    slug,
    name: slug,
    category: 'X',
    description: '',
    duration_minutes: minutes,
    price_from_pence: 100,
    price_to_pence: null,
    approval_mode: 'instant',
  }
}

it('parses repeated services and drops duplicates, keeping order', () => {
  expect(parseSelection('?services=a&services=b&services=a')).toEqual(['a', 'b'])
})

it('parses nothing from an empty search', () => {
  expect(parseSelection('')).toEqual([])
})

it('ignores blank services', () => {
  expect(parseSelection('?services=&services=a')).toEqual(['a'])
})

it('builds the query back', () => {
  expect(selectionQuery(['a', 'b'])).toBe('?services=a&services=b')
})

it('sums durations of the chosen services, ignoring unknown slugs', () => {
  const services = [service('a', 60), service('b', 180), service('c', 45)]
  expect(totalMinutes(services, ['a', 'b', 'nope'])).toBe(240)
})
