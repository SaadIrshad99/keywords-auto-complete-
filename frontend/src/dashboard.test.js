import assert from 'node:assert/strict'
import test from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

test('research form renders the backend-supported controls and defaults', async () => {
  const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
  try {
    const { default: ResearchForm } = await server.ssrLoadModule('/src/ResearchForm.jsx')
    const html = renderToStaticMarkup(createElement(ResearchForm, {
      onStart: () => {}, busy: false, disabled: false,
    }))
    for (const label of [
      'Seed keyword', 'Country', 'Language', 'Maximum depth', 'Request budget',
      'Alphabet suffix', 'Alphabet prefix', 'Numeric suffix', 'Numeric prefix',
      'Custom modifiers', 'Maximum unique keywords', 'Maximum pending queries',
      'Relevance filtering',
    ]) assert.ok(html.includes(label), label)
    assert.match(html, /<details class="rounded-xl/)
    assert.match(html, /value="us" selected=""/)
    assert.match(html, /value="en" selected=""/)
  } finally { await server.close() }
})

test('dashboard renders the restart warning and health state', async () => {
  const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
  try {
    const { default: App } = await server.ssrLoadModule('/src/App.jsx')
    const html = renderToStaticMarkup(createElement(App))
    assert.ok(html.includes('Unsaved keywords will be lost if the backend restarts'))
    assert.ok(html.includes('Checking backend'))
    assert.ok(html.includes('Ready when you are'))
  } finally { await server.close() }
})
