import assert from 'node:assert/strict'
import test from 'node:test'
import { ApiError, clearResearch, controlResearch, downloadCsv, getCurrentJob, getKeywords, startResearch } from './researchApi.js'

test('uses the implemented research paths and JSON payload', async () => {
  const calls = []
  const fake = async (url, options = {}) => {
    calls.push([url, options])
    return { ok: true, status: options.method === 'DELETE' ? 204 : 200, json: async () => ({ status: 'RUNNING' }) }
  }
  await startResearch({ seed: 'age calculator' }, fake)
  await getCurrentJob(fake)
  await controlResearch('pause', fake)
  await getKeywords({ offset: 25, limit: 25, filter: 'age & time' }, fake)
  await clearResearch(fake)
  assert.deepEqual(calls.map(([url]) => url), [
    '/api/research', '/api/research/current', '/api/research/current/pause',
    '/api/research/current/keywords?offset=25&limit=25&filter=age+%26+time',
    '/api/research/current',
  ])
  assert.equal(calls[0][1].method, 'POST')
  assert.deepEqual(JSON.parse(calls[0][1].body), { seed: 'age calculator' })
  assert.equal(calls[4][1].method, 'DELETE')
})

test('reports backend validation and unavailable errors', async () => {
  await assert.rejects(
    startResearch({}, async () => ({ ok: false, status: 422, json: async () => ({ detail: [{ msg: 'Invalid seed' }] }) })),
    (error) => error instanceof ApiError && error.status === 422 && error.message === 'Invalid seed',
  )
  await assert.rejects(
    getCurrentJob(async () => { throw new Error('offline') }),
    (error) => error instanceof ApiError && error.status === 0,
  )
})

test('downloads the server CSV blob and reports missing jobs', async () => {
  const blob = new Blob(['\ufeffKeyword\r\nage calculator\r\n'], { type: 'text/csv' })
  assert.equal(await downloadCsv(async (url) => {
    assert.equal(url, '/api/research/current/export')
    return { ok: true, blob: async () => blob }
  }), blob)
  await assert.rejects(
    downloadCsv(async () => ({ ok: false, status: 404, json: async () => ({ detail: 'no current research job' }) })),
    (error) => error.status === 404 && error.message === 'no current research job',
  )
})
