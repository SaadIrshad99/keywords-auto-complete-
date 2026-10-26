const BASE = '/api/research'

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request(path, options = {}, fetchImpl = fetch) {
  let response
  try {
    response = await fetchImpl(`${BASE}${path}`, options)
  } catch {
    throw new ApiError('Cannot reach the backend. Start it and try again.', 0)
  }
  if (!response.ok) {
    let detail
    try { detail = (await response.json()).detail } catch { /* A proxy may return plain text. */ }
    const message = typeof detail === 'string'
      ? detail
      : Array.isArray(detail) ? detail.map((item) => item.msg).join('; ')
        : `Request failed (${response.status}).`
    throw new ApiError(message, response.status)
  }
  return response.status === 204 ? null : response.json()
}

export const getCurrentJob = (fetchImpl) => request('/current', {}, fetchImpl)
export const startResearch = (payload, fetchImpl) => request('', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
}, fetchImpl)
export const controlResearch = (action, fetchImpl) => request(`/current/${action}`, { method: 'POST' }, fetchImpl)
export const clearResearch = (fetchImpl) => request('/current', { method: 'DELETE' }, fetchImpl)

export function getKeywords({ offset = 0, limit = 50, filter = '' } = {}, fetchImpl) {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
  if (filter.trim()) params.set('filter', filter.trim())
  return request(`/current/keywords?${params}`, {}, fetchImpl)
}

export async function downloadCsv(fetchImpl = fetch) {
  let response
  try { response = await fetchImpl(`${BASE}/current/export`) } catch {
    throw new ApiError('Cannot reach the backend. Start it and try again.', 0)
  }
  if (!response.ok) {
    let detail
    try { detail = (await response.json()).detail } catch { /* Keep a useful fallback. */ }
    throw new ApiError(typeof detail === 'string' ? detail : `Export failed (${response.status}).`, response.status)
  }
  return response.blob()
}
