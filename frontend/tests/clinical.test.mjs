import assert from 'node:assert/strict'
import { test } from 'node:test'
import { minuteLabel, patientTimeline, validateClinical, VITAL_LABELS } from '../src/utils/clinical.js'

function sample() {
  return { patient_id: 'ICU-1001', as_of_minutes: 360, model_profile: 'original', source: 'recorded_observations_and_staff_demo_entries',
    vitals: Object.keys(VITAL_LABELS).map((parameter) => ({ parameter, measurements: [] })),
    review_requests: {items: [], history: [], counts: {pending: 0, acknowledged: 0, resolved: 0, unassigned: 0}, truncated: false}, context: null, entries: [], context_history: [], rule_history: [], review_events: [], acknowledgements: [], assignments: [], rules: [], vital_warnings: [], follow_ups: { items: [], history: [], counts: {pending: 0, completed: 0, overdue: 0}, truncated: false } }
}
test('clinical views reject future readings, future notes and a response for another patient or time', () => {
  const data = sample()
  assert.equal(validateClinical(data, 'ICU-1001', 360, 'original'), data)
  for (const [id, minute, profile] of [['ICU-1002', 360, 'original'], ['ICU-1001', 720, 'original'], ['ICU-1001', 360, 'expanded']]) assert.throws(() => validateClinical(data, id, minute, profile))
  data.vitals[0].measurements.push({ value: 100, time_minutes: 361 })
  assert.throws(() => validateClinical(data, 'ICU-1001', 360, 'original'))
  data.vitals[0].measurements = []
  data.entries.push({ id: 1, minute: 361 })
  assert.throws(() => validateClinical(data, 'ICU-1001', 360, 'original'))
})
test('timeline distinguishes staff save dates from recorded time and hides future model points', () => {
  const data = sample()
  data.entries.push({ id: 1, minute: 100, kind: 'visit', assessment: 'Demo visit', author: 'Fictional Doctor', created_at: 9999999999, plan: 'Demo plan', review_minute: 300 })
  data.review_events.push({ id: 2, checkpoint: '6h', event_type: 'acknowledge', author: 'Nurse', content: 'Seen', created_at: 9999999999 })
  data.vitals[0].measurements.push({ value: 100, time_minutes: 300 })
  const patient = { available_through_minutes: 360, risk_trajectory: [{ checkpoint: '6h', assessment_status: 'READY', alert_state: 'WATCH' }, { checkpoint: '12h', assessment_status: 'NOT_YET_AVAILABLE' }] }
  const rows = patientTimeline(data, patient)
  assert.equal(rows.length, 4)
  assert.ok(rows.every((row) => row.minute <= 360))
  assert.equal(rows.find((row) => row.id === 'e-1').minute, 100)
  assert.equal(rows.find((row) => row.id === 'e-1').plan, 'Demo plan')
  assert.match(rows.find((row) => row.id === 'a-2').title, /acknowledged/)
  assert.equal(minuteLabel(375), '06:15')
})

test('follow-up validation rejects future or incomplete completion records', () => {
  const data = sample()
  const item = {entry_id: 1, event_id: 2, minute: 100, status: 'completed', status_minute: 300, status_saved_at: 1800000000, status_author: 'Fictional Nurse'}
  data.follow_ups.items.push(item)
  assert.equal(validateClinical(data, 'ICU-1001', 360, 'original'), data)
  item.status_minute = 361
  assert.throws(() => validateClinical(data, 'ICU-1001', 360, 'original'))
  item.status_minute = 300; item.status_author = null
  assert.throws(() => validateClinical(data, 'ICU-1001', 360, 'original'))
  item.status_author = 'Fictional Nurse'
  data.follow_ups.history.push({id: 2, minute: 400, status: 'completed', content: 'Demo completion'})
  assert.throws(() => validateClinical(data, 'ICU-1001', 360, 'original'))
  const rows = patientTimeline(data, {available_through_minutes: 360, risk_trajectory: []})
  assert.ok(!rows.some((row) => row.id === 'f-2'))
})

test('doctor review snapshots reject future requests and status changes', () => {
  const data = sample()
  data.review_requests.items.push({request_id: 1, entry_id: 1, minute: 100, event_id: 1, status: 'acknowledged', status_minute: 300})
  assert.equal(validateClinical(data, 'ICU-1001', 360, 'original'), data)
  data.review_requests.items[0].status_minute = 400
  assert.throws(() => validateClinical(data, 'ICU-1001', 360, 'original'))
})
