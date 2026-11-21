import { expect, it } from 'vitest'
import { linkify } from './linkify.ts'

const ORIGIN = 'https://demo.example'

it('turns links to this site into links, keeping the #t= fragment', () => {
  const text = `Manage it here: ${ORIGIN}/booking/ABCD-EFGH#t=tok_1-2\nThanks`
  expect(linkify(text, ORIGIN)).toEqual([
    'Manage it here: ',
    { href: `${ORIGIN}/booking/ABCD-EFGH#t=tok_1-2`, label: `${ORIGIN}/booking/ABCD-EFGH#t=tok_1-2` },
    '\nThanks',
  ])
})

it('leaves links to other sites as text', () => {
  const text = 'See https://evil.example/booking/X or http://demo.example.evil/x'
  expect(linkify(text, ORIGIN)).toEqual([text])
})

it('does not link a look-alike host that starts with our origin', () => {
  const text = 'Go to https://demo.example.evil/booking/X'
  expect(linkify(text, ORIGIN)).toEqual([text])
})

it('returns plain text unchanged', () => {
  expect(linkify('No links here.', ORIGIN)).toEqual(['No links here.'])
})
