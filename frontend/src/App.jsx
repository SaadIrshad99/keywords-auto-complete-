import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { checkBackendHealth } from './health.js'
import ResearchForm from './ResearchForm.jsx'
import { displayMethod, isActive, isFinished, shouldPoll } from './research.js'
import { ApiError, clearResearch, controlResearch, downloadCsv, getCurrentJob, getKeywords, startResearch } from './researchApi.js'

const PAGE_SIZE = 25
const card = 'rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6'
const secondaryButton = 'rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600'

function formatTime(value) {
  return value ? new Date(value).toLocaleString() : '—'
}

function Progress({ job, busy, onAction, onClear, onExport }) {
  const progress = Math.min(100, Math.round((job.requests_attempted / job.max_requests) * 100))
  const active = isActive(job.status)
  return <section className={card} aria-label="Research progress">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-indigo-600">Current research</p><h2 className="mt-1 text-xl font-semibold text-slate-950">{job.seed}</h2></div>
      <span className={`rounded-full px-3 py-1 text-xs font-bold tracking-wide ${job.status === 'FAILED' ? 'bg-rose-100 text-rose-800' : active ? 'bg-indigo-100 text-indigo-800' : 'bg-emerald-100 text-emerald-800'}`}>{job.status}</span>
    </div>
    <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
      {[
        ['Keywords', job.unique_keywords], ['Requests', `${job.requests_attempted} / ${job.max_requests}`],
        ['Current depth', `${job.current_depth} / ${job.max_depth}`], ['Pending queries', job.pending_queries],
      ].map(([label, value]) => <div className="rounded-xl bg-slate-50 p-3" key={label}><p className="text-xs text-slate-500">{label}</p><p className="mt-1 text-lg font-semibold text-slate-900">{value}</p></div>)}
    </div>
    <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100" role="progressbar" aria-label="Request budget used" aria-valuenow={job.requests_attempted} aria-valuemin={0} aria-valuemax={job.max_requests}><div className="h-full bg-indigo-500 transition-all" style={{ width: `${progress}%` }} /></div>
    <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-500"><span>Succeeded: {job.requests_succeeded}</span><span>Failed: {job.requests_failed}</span><span>Started: {formatTime(job.started_at)}</span>{job.ended_at && <span>Ended: {formatTime(job.ended_at)}</span>}</div>
    {job.current_query && <p className="mt-4 break-words rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-600">Current query: <span className="font-medium text-slate-800">{job.current_query}</span></p>}
    {job.stop_reason && <p className="mt-3 text-sm text-slate-600">Stop reason: <strong>{job.stop_reason.replaceAll('_', ' ')}</strong></p>}
    {job.queue_truncated && <p className="mt-2 text-sm text-amber-800">The pending queue limit dropped some expansion queries.</p>}
    {job.error_message && <p className="mt-2 text-sm text-rose-700" role="alert">{job.error_message}</p>}
    <div className="mt-5 flex flex-wrap gap-2">
      {['PENDING', 'RUNNING'].includes(job.status) && <button className={secondaryButton} disabled={busy} onClick={() => onAction('pause')}>Pause</button>}
      {job.status === 'PAUSED' && <button className={secondaryButton} disabled={busy} onClick={() => onAction('resume')}>Resume</button>}
      {active && <button className={secondaryButton} disabled={busy} onClick={() => onAction('cancel')}>Cancel</button>}
      <button className={secondaryButton} disabled={busy} onClick={onExport}>Export CSV</button>
      {isFinished(job.status) && <button className="rounded-lg border border-rose-200 px-3.5 py-2 text-sm font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50" disabled={busy || !job.ended_at} onClick={onClear}>Clear results</button>}
    </div>
  </section>
}

function Results({ page, offset, onOffset, search, onSearch, onApply, sort, onSort, loading }) {
  const rows = useMemo(() => {
    const items = [...(page?.items || [])]
    if (sort === 'keyword') items.sort((a, b) => a.keyword.localeCompare(b.keyword))
    if (sort === 'depth') items.sort((a, b) => a.depth - b.depth || a.keyword.localeCompare(b.keyword))
    return items
  }, [page, sort])
  const total = page?.total || 0
  return <section className={card} aria-label="Discovered keywords">
    <div className="flex flex-wrap items-end justify-between gap-3"><div><h2 className="text-lg font-semibold text-slate-950">Discovered keywords</h2><p className="mt-1 text-sm text-slate-500">{total.toLocaleString()} matching suggestions · original text from Google</p></div><span className="text-xs text-slate-500">{loading ? 'Updating…' : 'Live results'}</span></div>
    <form className="mt-5 flex flex-col gap-2 sm:flex-row" onSubmit={(event) => { event.preventDefault(); onApply() }}>
      <input className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" value={search} onChange={(event) => onSearch(event.target.value)} placeholder="Search keyword text" aria-label="Search keywords" maxLength={200} />
      <button className={secondaryButton} type="submit">Search</button>
      <select className={secondaryButton} value={sort} onChange={(event) => onSort(event.target.value)} aria-label="Sort current page"><option value="discovered">Discovery order</option><option value="keyword">Keyword A–Z</option><option value="depth">Depth</option></select>
    </form>
    <p className="mt-2 text-xs text-slate-500">Sorting applies to the current page. Search filters all collected keywords.</p>
    <div className="mt-4 overflow-x-auto rounded-xl border border-slate-200">
      <table className="min-w-[680px] w-full text-left text-sm"><thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr><th className="px-4 py-3">Keyword</th><th className="px-4 py-3">Depth</th><th className="px-4 py-3">First query</th><th className="px-4 py-3">Method</th><th className="px-4 py-3">Paths</th></tr></thead>
        <tbody className="divide-y divide-slate-100">{rows.map((item) => <tr key={item.keyword} className="align-top"><td className="break-words px-4 py-3 font-medium text-slate-900">{item.keyword}</td><td className="px-4 py-3 text-slate-600">{item.depth}</td><td className="break-words px-4 py-3 text-slate-600">{item.first_discovery_query}</td><td className="px-4 py-3 text-slate-600">{displayMethod(item.expansion_method)}</td><td className="px-4 py-3 text-slate-600"><details><summary className="cursor-pointer">{item.discoveries.length}</summary><ul className="mt-2 space-y-1 text-xs">{item.discoveries.map((path, index) => <li key={`${path.query}-${index}`}>{path.query} · {displayMethod(path.method)} · depth {path.depth}</li>)}</ul></details></td></tr>)}</tbody>
      </table>
      {!rows.length && <p className="p-8 text-center text-sm text-slate-500">{loading ? 'Loading keywords…' : 'No matching keywords yet.'}</p>}
    </div>
    <div className="mt-4 flex items-center justify-between gap-3 text-sm text-slate-500"><span>{total ? `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)} of ${total}` : '0 results'}</span><div className="flex gap-2"><button className={secondaryButton} disabled={offset === 0} onClick={() => onOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</button><button className={secondaryButton} disabled={offset + PAGE_SIZE >= total} onClick={() => onOffset(offset + PAGE_SIZE)}>Next</button></div></div>
  </section>
}

export default function App() {
  const [connection, setConnection] = useState('checking')
  const [job, setJob] = useState(null)
  const [page, setPage] = useState(null)
  const [offset, setOffset] = useState(0)
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('')
  const [sort, setSort] = useState('discovered')
  const [busy, setBusy] = useState(false)
  const [loadingResults, setLoadingResults] = useState(false)
  const [error, setError] = useState('')
  const generation = useRef(0)
  const operationInFlight = useRef(false)

  const refreshJob = useCallback(async () => {
    const token = generation.current
    try {
      const current = await getCurrentJob()
      if (token !== generation.current) return
      setJob(current)
      setConnection('connected')
    } catch (caught) {
      if (token !== generation.current) return
      if (caught instanceof ApiError && caught.status === 404) { setJob(null); setPage(null); setConnection('connected') }
      else { setConnection('unavailable'); setError(caught.message) }
    }
  }, [])

  const refreshResults = useCallback(async () => {
    if (!job) return
    const token = generation.current
    setLoadingResults(true)
    try {
      const results = await getKeywords({ offset, limit: PAGE_SIZE, filter })
      if (token === generation.current) setPage(results)
    } catch (caught) {
      if (token === generation.current) setError(caught.message)
    } finally { if (token === generation.current) setLoadingResults(false) }
  }, [job?.job_id, offset, filter])

  useEffect(() => {
    let alive = true
    async function connect() {
      const healthy = await checkBackendHealth()
      if (!alive) return
      setConnection(healthy ? 'connected' : 'unavailable')
      if (healthy) refreshJob()
    }
    connect()
    return () => { alive = false }
  }, [refreshJob])

  useEffect(() => { if (job) refreshResults() }, [job?.job_id, offset, filter, refreshResults])
  useEffect(() => {
    if (!shouldPoll(job)) return undefined
    const timer = setInterval(() => { refreshJob(); refreshResults() }, 2000)
    return () => clearInterval(timer)
  }, [job?.job_id, job?.status, job?.ended_at, refreshJob, refreshResults])

  async function run(operation) {
    if (operationInFlight.current) return
    operationInFlight.current = true
    setBusy(true)
    setError('')
    try { await operation() } catch (caught) {
      setError(caught.message)
      if (caught.status === 409 || caught.status === 404) await refreshJob()
    } finally { operationInFlight.current = false; setBusy(false) }
  }

  function start(payload) {
    run(async () => { const current = await startResearch(payload); generation.current += 1; setOffset(0); setFilter(''); setSearch(''); setPage(null); setJob(current) })
  }

  function action(name) { run(async () => { setJob(await controlResearch(name)); await refreshJob() }) }

  function clear() {
    if (!window.confirm('Clear this research? Export any keywords you want to keep first.')) return
    run(async () => { await clearResearch(); generation.current += 1; setJob(null); setPage(null); setOffset(0); setSearch(''); setFilter('') })
  }

  function exportCsv() {
    run(async () => {
      const blob = await downloadCsv()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'autocomplete-keywords.csv'
      document.body.append(link)
      link.click()
      link.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    })
  }

  return <main className="min-h-screen bg-slate-50 text-slate-900">
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-7 sm:py-9">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 pb-5"><div className="flex items-center gap-3"><span className="flex size-10 items-center justify-center rounded-xl bg-indigo-600 text-lg font-bold text-white" aria-hidden="true">A</span><span className="text-sm font-semibold tracking-wide">Keyword Research</span></div><div className="flex items-center gap-3"><span className={`rounded-full px-3 py-1 text-xs font-semibold ${connection === 'connected' ? 'bg-emerald-100 text-emerald-800' : connection === 'checking' ? 'bg-amber-100 text-amber-800' : 'bg-rose-100 text-rose-800'}`}>{connection === 'connected' ? 'Backend Connected' : connection === 'checking' ? 'Checking backend' : 'Backend Unavailable'}</span>{connection === 'unavailable' && <button className={secondaryButton} onClick={async () => { setError(''); setConnection('checking'); const healthy = await checkBackendHealth(); setConnection(healthy ? 'connected' : 'unavailable'); if (healthy) refreshJob() }}>Retry</button>}</div></header>
      <div className="py-8"><p className="text-xs font-semibold uppercase tracking-[0.2em] text-indigo-600">Local research workspace</p><h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">Autocomplete Keyword Research</h1><p className="mt-2 text-slate-600">Discover keyword ideas using Google Autocomplete.</p></div>
      <div className="mb-6 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950" role="note"><strong>Results are temporary.</strong> Unsaved keywords will be lost if the backend restarts. Export CSV before clearing or stopping it.</div>
      {error && <div className="mb-6 flex items-start justify-between gap-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800" role="alert"><span>{error}</span><button onClick={() => setError('')} aria-label="Dismiss error">×</button></div>}
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(330px,0.85fr)_minmax(0,1.5fr)]"><section className={card}><ResearchForm onStart={start} busy={busy} disabled={Boolean(job) || connection !== 'connected'} /></section><div className="space-y-6">{job ? <><Progress job={job} busy={busy} onAction={action} onClear={clear} onExport={exportCsv} /><Results page={page} offset={offset} onOffset={setOffset} search={search} onSearch={setSearch} onApply={() => { generation.current += 1; setOffset(0); setFilter(search.trim()) }} sort={sort} onSort={setSort} loading={loadingResults} /></> : <section className={card}><h2 className="text-lg font-semibold">Ready when you are</h2><p className="mt-2 text-sm leading-relaxed text-slate-600">Set up a seed keyword to collect Google Autocomplete suggestions. One research job can be kept at a time.</p></section>}</div></div>
      <footer className="mt-10 border-t border-slate-200 pt-5 text-xs text-slate-400">Local, single-user workspace · Google Suggest availability and localization may vary</footer>
    </div>
  </main>
}
