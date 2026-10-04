import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'
import { getPatientDetail, getPatients } from '../src/services/api.js'
import { assessmentLabel, formatScore } from '../src/utils/assessment.js'

const originalFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = originalFetch })

function assessment(checkpoint, status = 'READY') {
  return {
    checkpoint,
    assessment_status: status,
    assessment_reason: status === 'READY' ? null : 'No assessment is available.',
    temporal_observation_count: status === 'READY' ? 10 : 0,
    risk_probability: status === 'READY' ? 0.3 : null,
    risk_level: status === 'READY' ? 'LOW' : null,
    alert_state: status === 'READY' ? 'NO_ALERT' : null,
  }
}

function detail(asOf = 1440, statuses = ['READY', 'READY', 'READY']) {
  const points = ['6h', '12h', '24h'].map((checkpoint, index) => assessment(checkpoint, statuses[index]))
  const { checkpoint, ...primary } = points[1]
  return {
    ...primary, patient_id: 'ICU-1001', icu_type: 'MICU', primary_checkpoint: checkpoint,
    available_through_minutes: asOf,
    risk_trend: primary.assessment_status === 'READY' ? 'Stable' : null,
    risk_trajectory: points,
    vital_histories: ['HR', 'MAP', 'GCS', 'Creatinine'].map((parameter) => ({ parameter, measurements: [] })),
  }
}

function respond(payload) {
  globalThis.fetch = async () => ({ ok: true, headers: new Headers({ 'X-Silent-Window-Model': 'original' }), json: async () => payload })
}

test('missing scores never display as zero', () => {
  assert.equal(formatScore(null), 'Not assessed')
  assert.equal(formatScore(undefined), 'Not assessed')
  assert.equal(formatScore(0), '0.0000')
  assert.equal(formatScore(0.5499), '0.5499')
  assert.equal(assessmentLabel('INSUFFICIENT_DATA'), 'Insufficient data')
  assert.equal(assessmentLabel('NOT_YET_AVAILABLE'), 'Not available yet')
})

test('valid full historical detail is accepted', async () => {
  const payload = detail()
  respond(payload)
  assert.deepEqual(await getPatientDetail('ICU-1001'), payload)
})

test('eight-hour view sends time and accepts unavailable future checkpoints', async () => {
  const payload = detail(480, ['READY', 'NOT_YET_AVAILABLE', 'NOT_YET_AVAILABLE'])
  globalThis.fetch = async (url) => {
    assert.match(url, /as_of_minutes=480$/)
    return { ok: true, headers: new Headers({ 'X-Silent-Window-Model': 'original' }), json: async () => payload }
  }
  assert.deepEqual(await getPatientDetail('ICU-1001', { asOfMinutes: 480 }), payload)
})

test('static-only detail is accepted without a score or alert', async () => {
  const payload = detail(1440, Array(3).fill('INSUFFICIENT_DATA'))
  respond(payload)
  const result = await getPatientDetail('ICU-1001')
  assert.equal(result.risk_probability, null)
  assert.equal(result.alert_state, null)
})

test('calibrated detail requests carry model identity and historical time together', async () => {
  const payload = detail(480, ['READY', 'NOT_YET_AVAILABLE', 'NOT_YET_AVAILABLE'])
  globalThis.fetch = async (url) => {
    const params = new URL(url, 'http://127.0.0.1:5173').searchParams
    assert.equal(params.get('model_profile'), 'calibrated')
    assert.equal(params.get('as_of_minutes'), '480')
    return { ok: true, headers: new Headers({ 'X-Silent-Window-Model': 'calibrated' }), json: async () => payload }
  }
  assert.deepEqual(await getPatientDetail('ICU-1001', { modelProfile: 'calibrated', asOfMinutes: 480 }), payload)
})

test('unavailable result with a fake zero score is rejected', async () => {
  const payload = detail(1440, Array(3).fill('INSUFFICIENT_DATA'))
  payload.risk_trajectory[0].risk_probability = 0
  respond(payload)
  await assert.rejects(getPatientDetail('ICU-1001'), /unexpected response/)
})

test('future checkpoint marked ready is rejected', async () => {
  respond(detail(480))
  await assert.rejects(getPatientDetail('ICU-1001', { asOfMinutes: 480 }), /unexpected response/)
})

test('measurements after the selected time are rejected', async () => {
  const payload = detail(480, ['READY', 'NOT_YET_AVAILABLE', 'NOT_YET_AVAILABLE'])
  payload.vital_histories[0].measurements.push({ time_minutes: 481, value: 80 })
  respond(payload)
  await assert.rejects(getPatientDetail('ICU-1001', { asOfMinutes: 480 }), /unexpected response/)
})

test('primary score must match its trajectory checkpoint', async () => {
  const payload = detail()
  payload.risk_probability = 0.2
  respond(payload)
  await assert.rejects(getPatientDetail('ICU-1001'), /inconsistent primary assessment/)
})

test('a valid response for an earlier or later cutoff is rejected', async () => {
  for (const returned of [360, 720]) {
    respond(detail(returned, returned === 360 ? ['READY', 'NOT_YET_AVAILABLE', 'NOT_YET_AVAILABLE'] : ['READY', 'READY', 'NOT_YET_AVAILABLE']))
    await assert.rejects(getPatientDetail('ICU-1001', { asOfMinutes: 480 }), /mismatched recorded time/)
  }
})

test('invalid replay times fail before making a request', async () => {
  let requests = 0
  globalThis.fetch = async () => { requests += 1 }
  for (const asOfMinutes of [-1, 1441, 0.5, '360', NaN]) {
    await assert.rejects(getPatientDetail('ICU-1001', { asOfMinutes }), /whole minute/)
  }
  assert.equal(requests, 0)
})

test('unassessed patient summaries are accepted', async () => {
  const payload = {
    items: [{ ...assessment('12h', 'INSUFFICIENT_DATA'), patient_id: 'ICU-1001', icu_type: 'MICU', risk_trend: null }],
    page: 1, page_size: 25, total: 1, total_pages: 1, cohort_total: 1,
    cached_assessments: 1, result_scope: 'cohort', assessment_counts: null,
  }
  respond(payload)
  assert.deepEqual(await getPatients(), payload)
})
