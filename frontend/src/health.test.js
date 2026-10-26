import assert from 'node:assert/strict'
import test from 'node:test'
import { checkBackendHealth } from './health.js'

test('recognizes the expected backend health response', async () => {
  const available = await checkBackendHealth(async () => ({
    ok: true,
    json: async () => ({ status: 'ok', service: 'autocomplete-keyword-research' }),
  }))

  assert.equal(available, true)
})

test('reports the backend as unavailable on network failure', async () => {
  const available = await checkBackendHealth(async () => {
    throw new Error('Connection refused')
  })

  assert.equal(available, false)
})

test('rejects an unexpected health response', async () => {
  const available = await checkBackendHealth(async () => ({
    ok: true,
    json: async () => ({ status: 'error' }),
  }))

  assert.equal(available, false)
})
