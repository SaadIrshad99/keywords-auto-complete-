export async function checkBackendHealth(fetchImpl = fetch) {
  try {
    const response = await fetchImpl('/api/health')
    if (!response.ok) return false

    const data = await response.json()
    return data.status === 'ok' && data.service === 'autocomplete-keyword-research'
  } catch {
    return false
  }
}
