export const VITAL_LABELS = {
  SysABP: 'Systolic BP (invasive, mmHg)', DiasABP: 'Diastolic BP (invasive, mmHg)', MAP: 'MAP (invasive, mmHg)',
  NISysABP: 'Systolic BP (cuff, mmHg)', NIDiasABP: 'Diastolic BP (cuff, mmHg)', NIMAP: 'MAP (cuff, mmHg)',
  HR: 'Heart rate (bpm)', RespRate: 'Respiratory rate (breaths/min)', SaO2: 'Arterial oxygen saturation (%)',
  Temp: 'Temperature (°C)', GCS: 'GCS (/15)', Creatinine: 'Creatinine (mg/dL)',
}
export const ENTRY_LABELS = { visit: 'Doctor visit', assessment: 'Assessment', recommendation: 'Doctor recommendation', follow_up: 'Follow-up', handover: 'Handover', escalation: 'Escalation note (not routed)' }
export const minuteLabel = (minute) => `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`

export function patientTimeline(data, patient) {
  const rows = []
  for (const series of data.vitals) for (const item of series.measurements) rows.push({ id: `v-${series.parameter}-${item.time_minutes}`, minute: item.time_minutes, title: VITAL_LABELS[series.parameter], detail: String(item.value), source: 'Recorded measurement' })
  for (const item of data.context_history) rows.push({ id: `c-${item.id}`, minute: item.minute, title: 'Admission / condition updated', detail: `Diagnosis: ${item.diagnosis || 'Not provided'}\nAdmission reason: ${item.admission_reason || 'Not provided'}\nCondition: ${item.condition_summary || 'Not provided'}\nAdmission severity: ${item.admission_severity || 'Not provided'}\nSpecialty: ${item.specialty || 'Not provided'}\nResponsible doctor: ${item.physician_name || 'Not selected'}`, author: item.author, created_at: item.created_at, source: 'Staff demonstration record' })
  for (const item of data.follow_ups?.history || []) rows.push({ ...item, id: `f-${item.id}`, title: item.status === 'completed' ? 'Follow-up completed' : 'Follow-up reopened', detail: item.content, source: 'Staff demonstration record' })
  for (const item of data.review_requests?.history || []) rows.push({ ...item, id: `dr-${item.id}`, title: `Doctor review request #${item.request_id} · ${item.status}`, detail: item.content, source: 'Staff demonstration record' })
  for (const item of data.entries) rows.push({ ...item, id: `e-${item.id}`, title: data.review_requests?.items.some((request) => request.entry_id === item.id) ? 'Doctor review requested' : ENTRY_LABELS[item.kind], detail: item.assessment, source: 'Staff demonstration record' })
  for (const item of data.rule_history) rows.push({ ...item, id: `r-${item.id}`, title: 'Vital warning limits updated', detail: JSON.parse(item.rules_json).map((rule) => `${VITAL_LABELS[rule.parameter]}: ${rule.lower ?? 'no lower limit'} to ${rule.upper ?? 'no upper limit'}`).join('\n') || 'All demonstration vital warnings disabled.', source: 'Staff demonstration record' })
  for (const item of data.review_events) rows.push({ ...item, id: `a-${item.id}`, minute: parseInt(item.checkpoint, 10) * 60, title: item.event_type === 'acknowledge' ? 'Model warning acknowledged' : 'Model review entry', detail: item.content, source: 'Staff entry anchored to model checkpoint' })
  for (const item of patient.risk_trajectory) if (item.assessment_status !== 'NOT_YET_AVAILABLE') rows.push({ id: `m-${item.checkpoint}`, minute: parseInt(item.checkpoint, 10) * 60, title: `Model assessment · ${item.checkpoint}`, detail: item.alert_state?.replaceAll('_', ' ') || 'Insufficient data', source: 'Recorded checkpoint assessment' })
  return rows.filter((item) => item.minute <= patient.available_through_minutes).sort((a, b) => b.minute - a.minute || (b.created_at || 0) - (a.created_at || 0) || a.id.localeCompare(b.id))
}

export function validateClinical(data, patientId, minutes, modelProfile) {
  if (data?.patient_id !== patientId || data.as_of_minutes !== minutes || data.model_profile !== modelProfile
    || data.source !== 'recorded_observations_and_staff_demo_entries'
    || !Array.isArray(data.vitals) || data.vitals.length !== Object.keys(VITAL_LABELS).length
    || !data.vitals.every((series, index) => series.parameter === Object.keys(VITAL_LABELS)[index] && Array.isArray(series.measurements) && series.measurements.every((item, i) => Number.isInteger(item.time_minutes) && item.time_minutes >= 0 && item.time_minutes <= minutes && Number.isFinite(item.value) && item.value >= 0 && (i === 0 || item.time_minutes >= series.measurements[i - 1].time_minutes)))
    || !['entries', 'context_history', 'rule_history', 'review_events', 'acknowledgements', 'assignments', 'rules', 'vital_warnings'].every((key) => Array.isArray(data[key]))
    || ![...data.entries, ...data.context_history, ...data.rule_history].every((item) => Number.isInteger(item.minute) && item.minute >= 0 && item.minute <= minutes)
    || !data.review_requests || !Array.isArray(data.review_requests.items) || !Array.isArray(data.review_requests.history)
    || !['pending', 'acknowledged', 'resolved', 'unassigned'].every((key) => Number.isInteger(data.review_requests.counts?.[key]) && data.review_requests.counts[key] >= 0)
    || !data.review_requests.items.every((item) => Number.isInteger(item.request_id) && item.request_id > 0 && Number.isInteger(item.minute) && item.minute >= 0 && item.minute <= minutes && Number.isInteger(item.event_id) && item.event_id >= 0 && ['pending', 'acknowledged', 'resolved'].includes(item.status) && (item.status_minute == null || (Number.isInteger(item.status_minute) && item.status_minute >= item.minute && item.status_minute <= minutes)))
    || !data.review_requests.history.every((item) => Number.isInteger(item.minute) && item.minute >= 0 && item.minute <= minutes && ['pending', 'acknowledged', 'resolved'].includes(item.status))
    || !data.follow_ups || !Array.isArray(data.follow_ups.items) || !Array.isArray(data.follow_ups.history)
    || !['pending', 'completed', 'overdue'].every((key) => Number.isInteger(data.follow_ups.counts?.[key]) && data.follow_ups.counts[key] >= 0)
    || !data.follow_ups.items.every((item) => Number.isInteger(item.entry_id) && item.entry_id > 0 && ['pending', 'completed'].includes(item.status) && Number.isInteger(item.event_id) && item.event_id >= 0 && Number.isInteger(item.minute) && item.minute >= 0 && item.minute <= minutes && (item.status_minute == null || (Number.isInteger(item.status_minute) && item.status_minute >= item.minute && item.status_minute <= minutes)) && (item.status === 'pending' || (item.event_id > 0 && typeof item.status_author === 'string' && Number.isFinite(item.status_saved_at))))
    || !data.follow_ups.history.every((item) => Number.isInteger(item.minute) && item.minute >= 0 && item.minute <= minutes && ['pending', 'completed'].includes(item.status))
    || (data.context && (!Number.isInteger(data.context.minute) || data.context.minute > minutes || data.context.minute < 0))) throw new Error('Clinical API returned an unexpected recorded view. Reload and try again.')
  return data
}
