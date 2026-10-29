import assert from 'node:assert/strict'
import { test } from 'node:test'
import { validateReviewSummary, unseenReviewKeys } from '../src/utils/doctorReviews.js'
test('review notifications detect newly assigned older requests and reopened requests', () => {
  const seen = new Set(['30:0'])
  assert.deepEqual(unseenReviewKeys(['30:0', '12:0'], seen), ['12:0'])
  seen.add('12:0')
  assert.deepEqual(unseenReviewKeys(['30:0', '12:0'], seen), [])
  assert.deepEqual(unseenReviewKeys(['12:45'], seen), ['12:45'])
})
test('review notification responses require matching request identities and nonnegative counts', () => {
  const data = {open_count: 2, pending_ids: [30, 12], pending_keys: ['30:0', '12:45']}
  assert.equal(validateReviewSummary(data), data)
  for (const change of [{open_count: -1}, {pending_keys: ['12:0', '30:0']}, {pending_keys: ['30:0']}, {pending_keys: ['30:abc', '12:45']}]) assert.throws(() => validateReviewSummary({...data, ...change}))
})
