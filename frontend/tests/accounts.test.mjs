import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'
import { requestJson, setRequestCsrfToken } from '../src/services/api.js'
import { currentSession, savePreferences, getRequestSummary, saveRoleAssignment, issueRecovery, resetPassword } from '../src/services/accounts.js'
import { RecordedReplay } from '../src/utils/replay.js'

const originalFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = originalFetch; setRequestCsrfToken(null) })
const user = { id: 1, username: 'test-user', display_name: 'Test User', role: 'doctor', active: true,
  preferences: { preferred_model: 'expanded', page_size: 50, replay_step: 180 } }

test('private requests send cookie credentials and writes send the in-memory security token', async () => {
  setRequestCsrfToken('a'.repeat(64))
  globalThis.fetch = async (url, options) => {
    assert.equal(options.credentials, 'include')
    assert.equal(options.method, 'PATCH')
    assert.equal(options.headers['X-CSRF-Token'], 'a'.repeat(64))
    assert.deepEqual(JSON.parse(options.body), { display_name: 'Test User', ...user.preferences })
    return { ok: true, status: 200, json: async () => user }
  }
  assert.deepEqual(await savePreferences({ display_name: 'Test User', ...user.preferences }), user)
})
test('unknown role or missing security token cannot establish an authenticated UI', async () => {
  for (const payload of [{ user: { ...user, role: 'viewer' }, csrf_token: 'a'.repeat(64) }, { user, csrf_token: null }]) {
    globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => payload })
    await assert.rejects(currentSession(), /unexpected response/)
  }
})
test('server permission failures keep their clear message and logout accepts an empty response', async () => {
  globalThis.fetch = async () => ({ ok: false, status: 403, json: async () => ({ detail: 'This patient is not assigned to you.' }) })
  await assert.rejects(requestJson('/patients/ICU-1001'), /not assigned to you/)
  globalThis.fetch = async () => ({ ok: true, status: 204, json: async () => { throw new Error('must not parse') } })
  assert.equal(await requestJson('/auth/logout', { method: 'POST' }), null)
})
test('a saved replay speed applies when a patient session is created', () => {
  assert.equal(new RecordedReplay({ load: () => {}, initialStep: 180 }).getSnapshot().step, 180)
  assert.throws(() => new RecordedReplay({ load: () => {}, initialStep: 999 }), /Unsupported replay speed/)
})

test('notification API rejects invalid summaries rather than reporting a false zero', async () => {
  for (const payload of [{}, { pending_count: -1, latest_pending_id: 0 }, { pending_count: 1, latest_pending_id: 0 }]) {
    globalThis.fetch = async () => ({ ok: true, json: async () => payload })
    await assert.rejects(getRequestSummary(), /could not be read/)
  }
})

test('role assignment sends only the edited group, with no replacement of the other role', async () => {
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api/patients/ICU-1002/assignments/doctor')
    assert.equal(options.method, 'PATCH')
    assert.deepEqual(JSON.parse(options.body), { user_ids: [2, 3] })
    return { ok: true, json: async () => ({ patient_id: 'ICU-1002', assignments: [] }) }
  }
  await saveRoleAssignment('ICU-1002', 'doctor', [2, 3])
  assert.throws(() => saveRoleAssignment('ICU-1002', 'admin', []), /doctors or nurses/)
})

test('password recovery sends secrets only in the body and rejects a malformed issued code', async () => {
  const code = 'a'.repeat(43)
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api/accounts/2/password-recovery')
    assert.deepEqual(JSON.parse(options.body), { current_password: 'private administrator password' })
    return { ok: true, json: async () => ({ recovery_code: 'too-short', expires_at: 1800000000 }) }
  }
  await assert.rejects(issueRecovery(2, { current_password: 'private administrator password' }), /could not be read/)
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api/auth/reset-password')
    assert.deepEqual(JSON.parse(options.body), { username: 'doctor', recovery_code: code, password: 'private new password' })
    return { ok: true, json: async () => ({ message: 'Sign in with your new password.' }) }
  }
  assert.equal((await resetPassword({ username: 'doctor', recovery_code: code, password: 'private new password' })).message, 'Sign in with your new password.')
})
