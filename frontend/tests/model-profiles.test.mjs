import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'
import { getModelOptions, getGlobalIndexStatus, prepareGlobalIndex, getPatients, getSystemStatus } from '../src/services/api.js'

const originalFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = originalFetch })
const options = [
  { id: 'original', label: 'Original Random Forest', model_family: 'Random Forest V2', description: 'Historical research model', available: true, medium_threshold: 0.4, high_threshold: 0.55 },
  { id: 'calibrated', label: 'Calibrated research candidate', model_family: 'Calibrated Random Forest V3', description: 'Research candidate', available: true, medium_threshold: 0.12, high_threshold: 0.28 },
  { id: 'expanded', label: 'Five-checkpoint research candidate', model_family: 'Calibrated Random Forest V4', description: 'Research candidate', available: true, medium_threshold: 0.08, high_threshold: 0.28 },
]
const index = { state: 'not_started', total_patients: 3200, completed_patients: 0, message: 'Not started' }
const emptyPage = { items: [], page: 1, page_size: 25, total: 0, total_pages: 0, cohort_total: 3200, cached_assessments: 0, result_scope: 'cohort', assessment_counts: null }

test('model metadata accepts both versions and their distinct thresholds', async () => {
  globalThis.fetch = async () => ({ ok: true, json: async () => options })
  assert.deepEqual(await getModelOptions(), options)
})

test('unavailable candidate must not claim usable thresholds', async () => {
  globalThis.fetch = async () => ({ ok: true, json: async () => [options[0], { ...options[1], available: false }, options[2]] })
  await assert.rejects(getModelOptions(), /unexpected response/)
})

test('all assessment requests send the selected model and verify its identity', async () => {
  const requests = []
  globalThis.fetch = async (url, config) => {
    const parsed = new URL(url, 'http://127.0.0.1:5173')
    assert.equal(parsed.searchParams.get('model_profile'), 'calibrated')
    requests.push([parsed.pathname, config.method])
    return { ok: true, headers: new Headers({ 'X-Silent-Window-Model': 'calibrated' }), json: async () => parsed.pathname.endsWith('/patients') ? emptyPage : index }
  }
  await getPatients({ modelProfile: 'calibrated' })
  await getGlobalIndexStatus({ modelProfile: 'calibrated' })
  await prepareGlobalIndex({ modelProfile: 'calibrated' })
  assert.deepEqual(requests.map((entry) => entry[1]), ['GET', 'GET', 'POST'])
})

test('a response from the other model is rejected before displaying results', async () => {
  globalThis.fetch = async () => ({ ok: true, headers: new Headers({ 'X-Silent-Window-Model': 'original' }), json: async () => emptyPage })
  await assert.rejects(getPatients({ modelProfile: 'calibrated' }), /different or unidentified model/)
})

test('an unidentified assessment response is rejected', async () => {
  globalThis.fetch = async () => ({ ok: true, headers: new Headers(), json: async () => emptyPage })
  await assert.rejects(getPatients(), /different or unidentified model/)
})

test('health response must describe the selected model family', async () => {
  const health = { status: 'ok', api: 'online', models: 'ready', patient_data: 'available', model_family: 'Random Forest V2', primary_checkpoint: '12h', supported_checkpoints: ['6h', '12h', '24h'] }
  globalThis.fetch = async () => ({ ok: true, json: async () => health })
  await assert.rejects(getSystemStatus({ modelProfile: 'calibrated' }), /unexpected response/)
})

test('unknown client model profiles fail before a request is sent', async () => {
  globalThis.fetch = async () => { throw new Error('must not send') }
  await assert.rejects(getPatients({ modelProfile: 'unknown' }), /Unknown model/)
})
