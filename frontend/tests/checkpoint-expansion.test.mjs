import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'
import { getPatientDetail, getSystemStatus } from '../src/services/api.js'
import { nextReplayMinute, RecordedReplay } from '../src/utils/replay.js'

const originalFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = originalFetch })
const checkpoints = ['6h', '9h', '12h', '18h', '24h']
function detail(minutes) {
  const trajectory = checkpoints.map((checkpoint) => {
    const ready = parseInt(checkpoint) * 60 <= minutes
    return { checkpoint, assessment_status: ready ? 'READY' : 'NOT_YET_AVAILABLE',
      assessment_reason: ready ? null : 'Checkpoint has not been reached.', temporal_observation_count: ready ? 10 : 0,
      risk_probability: ready ? 0.2 : null, risk_level: ready ? 'MEDIUM' : null, alert_state: ready ? 'WATCH' : null }
  })
  const { checkpoint, ...primary } = trajectory[2]
  return { ...primary, primary_checkpoint: checkpoint, patient_id: 'ICU-1001', icu_type: 'MICU',
    available_through_minutes: minutes, risk_trend: minutes >= 720 ? 'Stable' : null,
    risk_trajectory: trajectory, vital_histories: ['HR', 'MAP', 'GCS', 'Creatinine'].map((parameter) => ({ parameter, measurements: [] })) }
}
function respond(payload) {
  globalThis.fetch = async () => ({ ok: true, headers: new Headers({ 'X-Silent-Window-Model': 'expanded' }), json: async () => payload })
}

test('expanded detail accepts five times and keeps 12h as the primary result', async () => {
  for (const minutes of [0, 480, 540, 720, 1080, 1440]) {
    const payload = detail(minutes)
    respond(payload)
    assert.deepEqual(await getPatientDetail('ICU-1001', { modelProfile: 'expanded', asOfMinutes: minutes }), payload)
  }
})
test('expanded profile rejects an omitted checkpoint or a visible future score', async () => {
  const missing = detail(1440)
  missing.risk_trajectory.splice(1, 1)
  respond(missing)
  await assert.rejects(getPatientDetail('ICU-1001', { modelProfile: 'expanded' }), /unexpected response/)
  respond(detail(1440))
  await assert.rejects(getPatientDetail('ICU-1001', { modelProfile: 'expanded', asOfMinutes: 540 }), /mismatched recorded time/)
  const future = detail(540)
  future.risk_trajectory[3] = detail(1440).risk_trajectory[3]
  respond(future)
  await assert.rejects(getPatientDetail('ICU-1001', { modelProfile: 'expanded', asOfMinutes: 540 }), /unexpected response/)
})
test('expanded health cannot claim the old three-time schema', async () => {
  const health = { status: 'ok', api: 'online', models: 'ready', patient_data: 'available', model_family: 'Calibrated Random Forest V4', primary_checkpoint: '12h', supported_checkpoints: checkpoints }
  respond(health)
  assert.deepEqual(await getSystemStatus({ modelProfile: 'expanded' }), health)
  respond({ ...health, supported_checkpoints: ['6h', '12h', '24h'] })
  await assert.rejects(getSystemStatus({ modelProfile: 'expanded' }), /unexpected response/)
})
test('expanded replay visits 9h and 18h even when resumed between checkpoints', () => {
  const minutes = checkpoints.map((cp) => parseInt(cp) * 60)
  assert.equal(nextReplayMinute(480, 180, minutes), 540)
  assert.equal(nextReplayMinute(1000, 180, minutes), 1080)
  const session = new RecordedReplay({ load: () => {}, checkpoints: minutes })
  assert.deepEqual(session.checkpoints, minutes)
  const visited = [480]
  while (visited.at(-1) < 1440) visited.push(nextReplayMinute(visited.at(-1), 180, minutes))
  for (const time of [540, 720, 1080, 1440]) assert.ok(visited.includes(time))
})
