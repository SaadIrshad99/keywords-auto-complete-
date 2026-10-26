import assert from 'node:assert/strict'
import test from 'node:test'
import { INITIAL_FORM, isActive, shouldPoll, validateResearchForm } from './research.js'

test('uses backend defaults and sends independent locale codes', () => {
  const { errors, payload } = validateResearchForm({
    ...INITIAL_FORM, seed: '  age   calculator  ', country: 'de', language: 'en',
  })
  assert.deepEqual(errors, {})
  assert.equal(payload.seed, 'age calculator')
  assert.equal(payload.country, 'de')
  assert.equal(payload.language, 'en')
  assert.equal(payload.max_depth, 2)
  assert.equal(payload.max_requests, 500)
  assert.equal(payload.request_delay, 1.5)
  assert.deepEqual(payload.methods, ['direct'])
})

test('rejects empty seed, missing methods, and unsupported numeric limits', () => {
  const { errors } = validateResearchForm({
    ...INITIAL_FORM, seed: ' ', methods: [], max_depth: 5,
    max_requests: 10001, max_keywords: 0, max_pending_queue: 100001,
    request_delay: -1,
  })
  for (const field of ['seed', 'methods', 'max_depth', 'max_requests', 'max_keywords', 'max_pending_queue', 'request_delay']) {
    assert.ok(errors[field], field)
  }
})

test('requires modifiers only for the modifier method and splits user text', () => {
  const missing = validateResearchForm({ ...INITIAL_FORM, seed: 'seed', methods: ['modifier_suffix'] })
  assert.ok(missing.errors.modifiers)
  const valid = validateResearchForm({
    ...INITIAL_FORM, seed: 'seed', methods: ['direct', 'modifier_suffix'],
    modifiers: 'online, free\nfor kids',
  })
  assert.deepEqual(valid.errors, {})
  assert.deepEqual(valid.payload.modifiers, ['online', 'free', 'for kids'])
  assert.equal(isActive('PAUSED'), true)
  assert.equal(isActive('COMPLETED'), false)
})

test('keeps polling until cancellation finishes its in-flight request', () => {
  assert.equal(shouldPoll({ status: 'RUNNING', ended_at: null }), true)
  assert.equal(shouldPoll({ status: 'CANCELLED', ended_at: null }), true)
  assert.equal(shouldPoll({ status: 'CANCELLED', ended_at: '2026-01-01T00:00:00Z' }), false)
  assert.equal(shouldPoll({ status: 'COMPLETED', ended_at: '2026-01-01T00:00:00Z' }), false)
})
