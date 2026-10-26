import { useState } from 'react'
import { COUNTRIES, INITIAL_FORM, LANGUAGES, METHODS, validateResearchForm } from './research.js'

const fieldClass = 'mt-1.5 w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm text-slate-900 shadow-sm outline-none transition focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'

function Field({ label, hint, error, children }) {
  return <div>
    <div className="flex items-baseline justify-between gap-3"><label className="text-sm font-semibold text-slate-800">{label}</label>{hint && <span className="text-xs text-slate-500">{hint}</span>}</div>
    {children}
    {error && <p className="mt-1 text-xs text-rose-700" role="alert">{error}</p>}
  </div>
}

export default function ResearchForm({ onStart, busy, disabled }) {
  const [form, setForm] = useState(INITIAL_FORM)
  const [errors, setErrors] = useState({})

  function update(field, value) {
    setForm((current) => ({ ...current, [field]: value }))
    setErrors((current) => ({ ...current, [field]: undefined }))
  }

  function toggleMethod(method) {
    setForm((current) => ({
      ...current,
      methods: current.methods.includes(method)
        ? current.methods.filter((item) => item !== method)
        : [...current.methods, method],
    }))
    setErrors((current) => ({ ...current, methods: undefined }))
  }

  function submit(event) {
    event.preventDefault()
    const { errors: nextErrors, payload } = validateResearchForm(form)
    setErrors(nextErrors)
    if (!Object.keys(nextErrors).length) onStart(payload)
  }

  return <form onSubmit={submit} className="space-y-6">
    <div>
      <h2 className="text-lg font-semibold text-slate-950">Set up research</h2>
      <p className="mt-1 text-sm text-slate-500">Choose a seed and how Google suggestions should expand.</p>
    </div>

    <Field label="Seed keyword" hint="Required" error={errors.seed}>
      <input className={fieldClass} value={form.seed} onChange={(event) => update('seed', event.target.value)} placeholder="e.g. age calculator" maxLength={250} aria-label="Seed keyword" aria-invalid={Boolean(errors.seed)} />
    </Field>

    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="Country">
        <select className={fieldClass} value={form.country} onChange={(event) => update('country', event.target.value)} aria-label="Country">
          {COUNTRIES.map(([code, name]) => <option value={code} key={code}>{name}</option>)}
        </select>
      </Field>
      <Field label="Language">
        <select className={fieldClass} value={form.language} onChange={(event) => update('language', event.target.value)} aria-label="Language">
          {LANGUAGES.map(([code, name]) => <option value={code} key={code}>{name}</option>)}
        </select>
      </Field>
    </div>
    <p className="-mt-4 text-xs text-slate-500">Country and language are independent Google localization hints.</p>

    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="Maximum depth" error={errors.max_depth}>
        <select className={fieldClass} value={form.max_depth} onChange={(event) => update('max_depth', event.target.value)} aria-label="Maximum depth">
          {[1, 2, 3, 4].map((depth) => <option value={depth} key={depth}>{depth} {depth === 1 ? 'level' : 'levels'}</option>)}
        </select>
      </Field>
      <Field label="Request budget" error={errors.max_requests}>
        <input className={fieldClass} type="number" min="1" max="10000" step="1" value={form.max_requests} onChange={(event) => update('max_requests', event.target.value)} aria-label="Request budget" />
      </Field>
    </div>
    <p className="-mt-4 text-xs text-slate-500">Deeper research can require more requests. Retries count toward the budget.</p>

    <fieldset>
      <legend className="text-sm font-semibold text-slate-800">Expansion methods</legend>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        {METHODS.map((method) => <label key={method.value} className="flex cursor-pointer items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-3 hover:border-indigo-300">
          <input type="checkbox" checked={form.methods.includes(method.value)} onChange={() => toggleMethod(method.value)} className="mt-1 accent-indigo-600" />
          <span><span className="block text-sm font-medium text-slate-800">{method.label}</span><span className="block text-xs text-slate-500">{method.hint}</span></span>
        </label>)}
      </div>
      {errors.methods && <p className="mt-1 text-xs text-rose-700" role="alert">{errors.methods}</p>}
    </fieldset>

    {form.methods.includes('modifier_suffix') && <Field label="Custom modifiers" hint="Comma or line separated" error={errors.modifiers}>
      <textarea className={fieldClass} rows="2" value={form.modifiers} onChange={(event) => update('modifiers', event.target.value)} placeholder="online, free, for" aria-label="Custom modifiers" />
    </Field>}

    <details className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <summary className="cursor-pointer text-sm font-semibold text-slate-800">Advanced settings</summary>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <Field label="Maximum unique keywords" error={errors.max_keywords}>
          <input className={fieldClass} type="number" min="1" max="100000" step="1" value={form.max_keywords} onChange={(event) => update('max_keywords', event.target.value)} aria-label="Maximum unique keywords" />
        </Field>
        <Field label="Maximum pending queries" error={errors.max_pending_queue}>
          <input className={fieldClass} type="number" min="1" max="100000" step="1" value={form.max_pending_queue} onChange={(event) => update('max_pending_queue', event.target.value)} aria-label="Maximum pending queries" />
        </Field>
        <Field label="Delay between requests" hint="Seconds" error={errors.request_delay}>
          <input className={fieldClass} type="number" min="0" max="60" step="0.1" value={form.request_delay} onChange={(event) => update('request_delay', event.target.value)} aria-label="Delay between requests" />
        </Field>
        <Field label="Relevance filtering">
          <select className={fieldClass} value={form.relevance} onChange={(event) => update('relevance', event.target.value)} aria-label="Relevance filtering">
            <option value="seed_phrase">Seed phrase</option><option value="seed_terms">Meaningful seed terms</option><option value="none">No filtering</option>
          </select>
        </Field>
      </div>
      <p className="mt-3 text-xs text-slate-500">Relevance controls which suggestions are expanded; all returned suggestions are collected. A shorter delay can trigger rate limits.</p>
    </details>

    <button type="submit" disabled={busy || disabled} className="w-full rounded-xl bg-indigo-600 px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-300 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600">
      {busy ? 'Starting research…' : 'Start research'}
    </button>
    {disabled && <p className="text-center text-xs text-slate-500">Clear the current job before starting another.</p>}
  </form>
}
