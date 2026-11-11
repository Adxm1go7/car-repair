import { expect, it } from 'vitest'
import { formatDuration, formatPrice } from './format.ts'

it.each([
  [21900, null, '£219'],
  [5485, null, '£54.85'],
  [45000, 75000, '£450–£750'],
  [12000, 12000, '£120'],
  [9050, 18000, '£90.50–£180'],
  [0, null, '£0'],
])('formatPrice(%i, %s) is %s', (from, to, expected) => {
  expect(formatPrice(from, to)).toBe(expected)
})

it.each([
  [30, '30m'],
  [45, '45m'],
  [60, '1h'],
  [90, '1h 30m'],
  [360, '6h'],
])('formatDuration(%i) is %s', (minutes, expected) => {
  expect(formatDuration(minutes)).toBe(expected)
})
