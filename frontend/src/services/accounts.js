import { ApiError, requestJson } from './api.js'
import { ROLE_LABELS } from '../permissions.js'

export function validateUser(user) {
  if (!user || !Number.isInteger(user.id) || user.id < 1 || !Object.hasOwn(ROLE_LABELS, user.role)
    || typeof user.username !== 'string' || typeof user.display_name !== 'string' || user.active !== true
    || !['original', 'calibrated', 'expanded'].includes(user.preferences?.preferred_model)
    || ![25, 50, 100].includes(user.preferences?.page_size) || ![15, 60, 180].includes(user.preferences?.replay_step)) {
    throw new ApiError('Account API returned an unexpected response')
  }
  return user
}
function validateSession(payload) {
  validateUser(payload?.user)
  if (typeof payload.csrf_token !== 'string' || !/^[a-f0-9]{64}$/.test(payload.csrf_token)) throw new ApiError('Session API returned an unexpected response')
  return payload
}
export async function authStatus(signal) {
  const data = await requestJson('/auth/status', { signal })
  if (typeof data?.setup_required !== 'boolean') throw new ApiError('Setup status could not be read')
  return data
}
export async function currentSession(signal) { return validateSession(await requestJson('/auth/me', { signal })) }
export async function signIn(body, setup = false) { return validateSession(await requestJson(setup ? '/auth/setup' : '/auth/login', { method: 'POST', body })) }
export function signOut() { return requestJson('/auth/logout', { method: 'POST' }) }
export async function savePreferences(body) { return validateUser(await requestJson('/account/preferences', { method: 'PATCH', body })) }
export function listAccounts(signal) { return requestJson('/accounts', { signal }) }
export function requestAccount(body) { return requestJson('/auth/register', { method: 'POST', body }) }
export function listPermissionRequests(status, offset, signal) { return requestJson(`/permissions?status=${status}&offset=${offset}&limit=50`, { signal }) }
export async function getRequestSummary(signal) {
  const data = await requestJson('/permissions/summary', { signal })
  if (!Number.isInteger(data?.pending_count) || data.pending_count < 0 || !Number.isInteger(data.latest_pending_id) || data.latest_pending_id < 0
    || (data.pending_count === 0) !== (data.latest_pending_id === 0)) throw new ApiError('Request count could not be read')
  return data
}
export async function reviewPermissionRequest(id, body) {
  const result = await requestJson(`/permissions/${id}/review`, { method: 'POST', body })
  if (typeof window !== 'undefined') window.dispatchEvent(new Event('silent-window-requests-changed'))
  return result
}
export function updateAccount(id, body) { return requestJson(`/accounts/${id}`, { method: 'PATCH', body }) }
export function changePassword(body) { return requestJson('/account/password', { method: 'POST', body }) }
export async function issueRecovery(id, body) {
  const data = await requestJson(`/accounts/${id}/password-recovery`, { method: 'POST', body })
  if (typeof data?.recovery_code !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(data.recovery_code)
    || !Number.isFinite(data.expires_at)) throw new ApiError('The recovery code could not be read')
  return data
}
export function resetPassword(body) { return requestJson('/auth/reset-password', { method: 'POST', body }) }
export function getStaff(signal) { return requestJson('/team/staff', { signal }) }
export function getWorkflow(patientId, modelProfile, minutes, signal) {
  return requestJson(`/patients/${encodeURIComponent(patientId)}/workflow?model_profile=${modelProfile}&as_of_minutes=${minutes}`, { signal })
}
export function saveAssignment(patientId, userIds) { return requestJson(`/patients/${encodeURIComponent(patientId)}/assignments`, { method: 'PUT', body: { user_ids: userIds } }) }
export function saveRoleAssignment(patientId, role, userIds) {
  if (!['doctor', 'nurse'].includes(role)) throw new ApiError('Choose doctors or nurses')
  return requestJson(`/patients/${encodeURIComponent(patientId)}/assignments/${role}`, { method: 'PATCH', body: { user_ids: userIds } })
}
export function addPatientEvent(patientId, body) { return requestJson(`/patients/${encodeURIComponent(patientId)}/events`, { method: 'POST', body }) }
