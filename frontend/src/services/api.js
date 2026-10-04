const configuredBaseUrl = import.meta.env?.VITE_API_BASE_URL

export const API_BASE_URL = (
  configuredBaseUrl || '/api'
).replace(/\/$/, '')

export function modelCheckpoints(profile = 'original') {
  return profile === 'expanded' ? ['6h', '9h', '12h', '18h', '24h'] : ['6h', '12h', '24h']
}
const CHECKPOINT_MINUTES = { '6h': 360, '9h': 540, '12h': 720, '18h': 1080, '24h': 1440 }
const DETAIL_VITALS = ['HR', 'MAP', 'GCS', 'Creatinine']
const RISK_LEVELS = new Set(['LOW', 'MEDIUM', 'HIGH'])
const ALERT_STATES = new Set(['NO_ALERT', 'WATCH', 'HIGH_ALERT'])
const HEALTH_STATES = new Set(['ok', 'degraded'])
const GLOBAL_INDEX_STATES = new Set(['not_started', 'building', 'ready', 'failed'])
const MODEL_FAMILIES = {
  original: 'Random Forest V2',
  calibrated: 'Calibrated Random Forest V3',
  expanded: 'Calibrated Random Forest V4',
}

function profileParams(modelProfile) {
  if (!Object.hasOwn(MODEL_FAMILIES, modelProfile)) throw new ApiError('Unknown model version')
  return new URLSearchParams({ model_profile: modelProfile })
}

export class ApiError extends Error {
  constructor(message, status = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

let requestCsrfToken = null
export function setRequestCsrfToken(token) { requestCsrfToken = token }

export async function requestJson(path, { signal, method = 'GET', expectedModelProfile, body } = {}) {
  let response
  try {
    const headers = {}
    if (body !== undefined) headers['Content-Type'] = 'application/json'
    if (method !== 'GET' && requestCsrfToken) headers['X-CSRF-Token'] = requestCsrfToken
    response = await fetch(`${API_BASE_URL}${path}`, { method, signal, credentials: 'include', headers,
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}) })
  } catch (error) {
    if (error?.name === 'AbortError') throw error
    throw new ApiError('The backend could not be reached')
  }

  if (!response.ok) {
    if (response.status === 401 && typeof window !== 'undefined') {
      window.dispatchEvent(new Event('silent-window-session-ended'))
    }
    let detail
    try { detail = (await response.json()).detail } catch { /* A non-JSON failure still has a safe message. */ }
    const message = typeof detail === 'string' && detail.length <= 240 ? detail : response.status === 401
      ? 'Your session ended. Please sign in again.'
      : response.status === 403 ? 'This action is not allowed for your account.'
      : response.status === 404
      ? 'Patient is not in the available cohort.'
      : response.status === 409
        ? 'Complete patient assessments are not ready.'
        : 'The API could not complete this request.'
    throw new ApiError(message, response.status)
  }

  if (response.status === 204) return null

  if (expectedModelProfile && response.headers?.get('X-Silent-Window-Model') !== expectedModelProfile) {
    throw new ApiError('The API returned a different or unidentified model version')
  }
  try {
    return await response.json()
  } catch {
    throw new ApiError('The API returned an invalid response', response.status)
  }
}

function isProbability(value) {
  return Number.isFinite(value) && value >= 0 && value <= 1
}

function isAssessment(payload) {
  if (!payload || !Number.isInteger(payload.temporal_observation_count)
    || payload.temporal_observation_count < 0) return false
  if (payload.assessment_status === 'READY') {
    return payload.temporal_observation_count > 0
      && payload.assessment_reason === null
      && isProbability(payload.risk_probability)
      && RISK_LEVELS.has(payload.risk_level)
      && ALERT_STATES.has(payload.alert_state)
  }
  return ['INSUFFICIENT_DATA', 'NOT_YET_AVAILABLE'].includes(payload.assessment_status)
    && typeof payload.assessment_reason === 'string'
    && payload.assessment_reason.length > 0
    && payload.risk_probability === null
    && payload.risk_level === null
    && payload.alert_state === null
    && payload.temporal_observation_count === 0
}

function isTrend(value) {
  return value === null || ['Rising', 'Stable', 'Falling'].includes(value)
}

function isPatientSummary(payload) {
  return payload
    && typeof payload.patient_id === 'string'
    && typeof payload.icu_type === 'string'
    && payload.checkpoint === '12h'
    && isAssessment(payload)
    && isTrend(payload.risk_trend)
    && (payload.assessment_status === 'READY' || payload.risk_trend === null)
}

function validatePatientPage(payload) {
  const validItems = Array.isArray(payload?.items)
    && payload.items.every(isPatientSummary)
  const validScope = [
    'cohort',
    'cached_assessments',
    'complete_assessment_index',
  ].includes(
    payload?.result_scope,
  )
  const counts = payload?.assessment_counts
  const validCounts = counts === null || (
    counts
    && Number.isInteger(counts.high_risk)
    && counts.high_risk >= 0
    && Number.isInteger(counts.watch)
    && counts.watch >= 0
    && Number.isInteger(counts.no_alert)
    && counts.no_alert >= 0
    && Number.isInteger(counts.not_assessed)
    && counts.not_assessed >= 0
  )
  if (
    !validItems
    || !Number.isInteger(payload.page)
    || !Number.isInteger(payload.page_size)
    || !Number.isInteger(payload.total)
    || !Number.isInteger(payload.total_pages)
    || !Number.isInteger(payload.cohort_total)
    || !Number.isInteger(payload.cached_assessments)
    || !validScope
    || !validCounts
  ) {
    throw new ApiError('Patient API returned an unexpected response')
  }
  return payload
}

function validateGlobalIndexStatus(payload) {
  if (
    !payload
    || !GLOBAL_INDEX_STATES.has(payload.state)
    || !Number.isInteger(payload.total_patients)
    || payload.total_patients < 0
    || !Number.isInteger(payload.completed_patients)
    || payload.completed_patients < 0
    || payload.completed_patients > payload.total_patients
    || typeof payload.message !== 'string'
  ) {
    throw new ApiError('Assessment index API returned an unexpected response')
  }
  return payload
}

function validatePatientDetail(payload, modelProfile) {
  const checkpoints = modelCheckpoints(modelProfile)
  const trajectory = payload?.risk_trajectory
  const histories = payload?.vital_histories
  const trajectoryIsValid = Array.isArray(trajectory)
    && trajectory.length === checkpoints.length
    && trajectory.every((point, index) => (
      point?.checkpoint === checkpoints[index]
      && isAssessment(point)
      && ((CHECKPOINT_MINUTES[point.checkpoint] > payload.available_through_minutes)
        === (point.assessment_status === 'NOT_YET_AVAILABLE'))
    ))
  const historiesAreValid = Array.isArray(histories)
    && histories.length === DETAIL_VITALS.length
    && histories.every((series, index) => (
      series?.parameter === DETAIL_VITALS[index]
      && Array.isArray(series.measurements)
      && series.measurements.every((measurement) => (
        Number.isFinite(measurement?.time_minutes)
        && measurement.time_minutes >= 0
        && measurement.time_minutes <= payload.available_through_minutes
        && Number.isFinite(measurement.value)
      ))
    ))

  if (
    !payload
    || typeof payload.patient_id !== 'string'
    || typeof payload.icu_type !== 'string'
    || payload.primary_checkpoint !== '12h'
    || !Number.isInteger(payload.available_through_minutes)
    || payload.available_through_minutes < 0
    || payload.available_through_minutes > 1440
    || !isAssessment(payload)
    || !isTrend(payload.risk_trend)
    || (payload.assessment_status !== 'READY' && payload.risk_trend !== null)
    || !trajectoryIsValid
    || !historiesAreValid
  ) {
    throw new ApiError('Patient detail API returned an unexpected response')
  }
  const primary = trajectory.find((point) => point.checkpoint === '12h')
  if (['risk_probability', 'risk_level', 'alert_state', 'assessment_status',
    'assessment_reason', 'temporal_observation_count'].some((key) => payload[key] !== primary[key])) {
    throw new ApiError('Patient detail API returned an inconsistent primary assessment')
  }
  return payload
}

function validateSystemStatus(payload, modelProfile) {
  const checkpoints = modelCheckpoints(modelProfile)
  if (
    !payload
    || !HEALTH_STATES.has(payload.status)
    || payload.api !== 'online'
    || !['ready', 'unavailable'].includes(payload.models)
    || !['available', 'unavailable'].includes(payload.patient_data)
    || payload.model_family !== MODEL_FAMILIES[modelProfile]
    || payload.primary_checkpoint !== '12h'
    || !Array.isArray(payload.supported_checkpoints)
    || payload.supported_checkpoints.length !== checkpoints.length
    || !payload.supported_checkpoints.every(
      (checkpoint, index) => checkpoint === checkpoints[index],
    )
  ) {
    throw new ApiError('System status API returned an unexpected response')
  }
  return payload
}

export async function getModelOptions({ signal } = {}) {
  const payload = await requestJson('/models', { signal })
  if (!Array.isArray(payload) || payload.length !== 3
    || new Set(payload.map((option) => option?.id)).size !== 3
    || !payload.every((option) => (
      option && Object.hasOwn(MODEL_FAMILIES, option.id)
      && option.model_family === MODEL_FAMILIES[option.id]
      && typeof option.label === 'string' && typeof option.description === 'string'
      && typeof option.available === 'boolean'
      && (option.available
        ? isProbability(option.medium_threshold) && isProbability(option.high_threshold)
          && option.medium_threshold < option.high_threshold
        : option.medium_threshold === null && option.high_threshold === null)
    ))) {
    throw new ApiError('Model versions API returned an unexpected response')
  }
  return payload
}

export async function getSystemStatus({ signal, modelProfile = 'original' } = {}) {
  const payload = await requestJson(`/health?${profileParams(modelProfile)}`, { signal })
  return validateSystemStatus(payload, modelProfile)
}

export async function getPatients({
  page = 1,
  pageSize = 25,
  search = '',
  risk = '',
  alert = '',
  scope = 'page',
  sortOrder = 'asc',
  modelProfile = 'original',
  signal,
} = {}) {
  const params = new URLSearchParams({
    ...Object.fromEntries(profileParams(modelProfile)),
    page: String(page),
    page_size: String(pageSize),
    sort_by: 'patient_id',
    sort_order: sortOrder,
    scope,
  })
  if (search.trim()) params.set('search', search.trim())
  if (risk) params.set('risk', risk)
  if (alert) params.set('alert', alert)
  const payload = await requestJson(`/patients?${params}`, { signal, expectedModelProfile: modelProfile })
  return validatePatientPage(payload)
}

export async function getGlobalIndexStatus({ signal, modelProfile = 'original' } = {}) {
  const payload = await requestJson(`/patients/global-index/status?${profileParams(modelProfile)}`, { signal, expectedModelProfile: modelProfile })
  return validateGlobalIndexStatus(payload)
}

export async function prepareGlobalIndex({ signal, modelProfile = 'original' } = {}) {
  const payload = await requestJson(`/patients/global-index/prepare?${profileParams(modelProfile)}`, {
    method: 'POST',
    signal,
    expectedModelProfile: modelProfile,
  })
  return validateGlobalIndexStatus(payload)
}

export async function getPatientDetail(patientId, { signal, asOfMinutes = 1440, modelProfile = 'original' } = {}) {
  if (!Number.isInteger(asOfMinutes) || asOfMinutes < 0 || asOfMinutes > 1440) {
    throw new ApiError('Recorded time must be a whole minute between 0 and 1440')
  }
  const params = profileParams(modelProfile)
  params.set('as_of_minutes', String(asOfMinutes))
  const payload = await requestJson(
    `/patients/${encodeURIComponent(patientId)}?${params}`,
    { signal, expectedModelProfile: modelProfile },
  )
  const detail = validatePatientDetail(payload, modelProfile)
  if (detail.patient_id !== patientId) {
    throw new ApiError('Patient detail API returned a mismatched patient ID')
  }
  if (detail.available_through_minutes !== asOfMinutes) {
    throw new ApiError('Patient detail API returned a mismatched recorded time')
  }
  return detail
}
