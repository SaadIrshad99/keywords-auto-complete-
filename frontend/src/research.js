export const METHODS = [
  { value: 'direct', label: 'Direct seed', hint: 'Ask Google about the seed itself.' },
  { value: 'alphabet_suffix', label: 'Alphabet suffix', hint: 'Add a through z after each keyword.' },
  { value: 'alphabet_prefix', label: 'Alphabet prefix', hint: 'Add a through z before each keyword.' },
  { value: 'numeric_suffix', label: 'Numeric suffix', hint: 'Add 0 through 9 after each keyword.' },
  { value: 'numeric_prefix', label: 'Numeric prefix', hint: 'Add 0 through 9 before each keyword.' },
  { value: 'modifier_suffix', label: 'Custom modifiers', hint: 'Add your own words after each keyword.' },
]

export const COUNTRIES = [
  ['us', 'United States'], ['gb', 'United Kingdom'], ['ca', 'Canada'],
  ['au', 'Australia'], ['de', 'Germany'], ['fr', 'France'], ['es', 'Spain'],
  ['it', 'Italy'], ['br', 'Brazil'], ['mx', 'Mexico'], ['in', 'India'],
  ['pk', 'Pakistan'], ['sa', 'Saudi Arabia'], ['ae', 'United Arab Emirates'],
  ['jp', 'Japan'], ['kr', 'South Korea'], ['nl', 'Netherlands'],
]

export const LANGUAGES = [
  ['en', 'English'], ['de', 'German'], ['fr', 'French'], ['es', 'Spanish'],
  ['pt', 'Portuguese'], ['ar', 'Arabic'], ['hi', 'Hindi'], ['ur', 'Urdu'],
  ['ja', 'Japanese'], ['ko', 'Korean'], ['nl', 'Dutch'], ['it', 'Italian'],
]

export const INITIAL_FORM = {
  seed: '', country: 'us', language: 'en', max_depth: 2, max_requests: 500,
  max_keywords: 10000, max_pending_queue: 1000, request_delay: 1.5,
  methods: ['direct'], modifiers: '', relevance: 'seed_phrase',
}

const integerLimits = {
  max_depth: [1, 4], max_requests: [1, 10000],
  max_keywords: [1, 100000], max_pending_queue: [1, 100000],
}

export function validateResearchForm(form) {
  const errors = {}
  const seed = form.seed.trim().replace(/\s+/g, ' ')
  if (!seed) errors.seed = 'Enter a seed keyword.'
  else if (seed.length > 200) errors.seed = 'Use 200 characters or fewer.'
  for (const [field, [min, max]] of Object.entries(integerLimits)) {
    const value = Number(form[field])
    if (!Number.isInteger(value) || value < min || value > max || String(form[field]).trim() === '') {
      errors[field] = `Enter a whole number from ${min} to ${max}.`
    }
  }
  const delay = Number(form.request_delay)
  if (!Number.isFinite(delay) || delay < 0 || delay > 60 || String(form.request_delay).trim() === '') {
    errors.request_delay = 'Enter a delay from 0 to 60 seconds.'
  }
  if (!form.methods.length) errors.methods = 'Select at least one expansion method.'
  const modifiers = form.modifiers.split(/[\n,]+/).map((item) => item.trim().replace(/\s+/g, ' ')).filter(Boolean)
  if (modifiers.length > 50) errors.modifiers = 'Use at most 50 modifiers.'
  if (form.methods.includes('modifier_suffix') && !modifiers.length) {
    errors.modifiers = 'Add at least one modifier when this method is selected.'
  }
  return { errors, payload: {
    seed, country: form.country, language: form.language,
    max_depth: Number(form.max_depth), max_requests: Number(form.max_requests),
    max_keywords: Number(form.max_keywords), max_pending_queue: Number(form.max_pending_queue),
    request_delay: delay, methods: form.methods, modifiers, relevance: form.relevance,
  } }
}

export function isActive(status) {
  return ['PENDING', 'RUNNING', 'PAUSED'].includes(status)
}

export function isFinished(status) {
  return ['COMPLETED', 'CANCELLED', 'FAILED'].includes(status)
}

export function shouldPoll(job) {
  // Cancellation can be visible before the in-flight request has stopped.
  return Boolean(job && (!isFinished(job.status) || !job.ended_at))
}

export function displayMethod(method) {
  return METHODS.find((item) => item.value === method)?.label || method
}
