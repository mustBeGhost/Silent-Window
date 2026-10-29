import { useEffect, useState } from 'react'
import { useAuth } from '../context/Auth'
import { requestJson } from '../services/api'
import { ENTRY_LABELS, VITAL_LABELS, minuteLabel, patientTimeline, validateClinical } from '../utils/clinical'
import VitalChart from './VitalChart'
import FollowUps from './FollowUps'
import DoctorReviews from './DoctorReviews'

const CONTEXT_FIELDS = { diagnosis: 'Admission diagnosis', admission_reason: 'Reason for ICU admission', condition_summary: 'Current condition / clinical synopsis', admission_severity: 'Severity at admission', specialty: 'Consulting team / specialty' }
const WARNING_LABELS = { OUTSIDE_ENTERED_LIMITS: 'Outside entered limits', WITHIN_ENTERED_LIMITS: 'Within entered limits', NO_READING_AFTER_RULE: 'No reading since these limits were entered' }

export default function ClinicalWorkspace({ patient, modelProfile }) {
  const { user } = useAuth()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)
  const [revision, setRevision] = useState(0)
  const [timelineFilter, setTimelineFilter] = useState('all')
  const minute = patient.available_through_minutes
  const base = `/patients/${encodeURIComponent(patient.patient_id)}/clinical`
  useEffect(() => {
    if (!user) return undefined
    const controller = new AbortController()
    requestJson(`${base}?as_of_minutes=${minute}&model_profile=${modelProfile}`, { signal: controller.signal })
      .then((payload) => { if (!controller.signal.aborted) { setData(validateClinical(payload, patient.patient_id, minute, modelProfile)); setError(null) } })
      .catch((failure) => { if (!controller.signal.aborted) { setError(failure.message); if (failure.status === 403) setData(null) } })
    return () => controller.abort()
  }, [base, minute, modelProfile, revision, user?.id])
  useEffect(() => {
    const refresh = () => setRevision((value) => value + 1)
    window.addEventListener('silent-window-workflow-changed', refresh)
    return () => window.removeEventListener('silent-window-workflow-changed', refresh)
  }, [])
  useEffect(() => {
    if (data && /^#patient-[a-z-]+$/.test(window.location.hash)) document.getElementById(window.location.hash.slice(1))?.scrollIntoView({ block: 'start' })
  }, [base, Boolean(data)])
  async function save(event, path, body) {
    event.preventDefault(); const form = event.currentTarget
    setBusy(true); setError(null); setMessage(null)
    try {
      await requestJson(`${base}/${path}`, { method: 'POST', body: { ...body, as_of_minutes: minute } })
      if (path === 'entries' || path === 'review-requests') form.reset()
      window.dispatchEvent(new Event('silent-window-reviews-changed'))
      setMessage('Saved as a staff-entered demonstration record. Earlier versions are kept.')
      setRevision((value) => value + 1)
    } catch (failure) { setError(failure.message) }
    finally { setBusy(false) }
  }
  if (!user) return null
  const canContext = ['admin', 'coordinator', 'doctor'].includes(user.role)
  const canNotes = ['doctor', 'nurse', 'coordinator'].includes(user.role)
  const noteKinds = user.role === 'doctor' ? Object.keys(ENTRY_LABELS) : ['follow_up', 'handover', 'escalation']
  const timeInput = <label>Recorded minute after admission<input name="minute" type="number" min="0" max={minute} step="1" required defaultValue={minute} /></label>
  const timeline = data ? patientTimeline(data, patient).filter((item) => timelineFilter === 'all' || (timelineFilter === 'staff' ? item.source.startsWith('Staff') : !item.source.startsWith('Staff'))) : []
  return <section id="patient-clinical-context" className="panel clinical-workspace">
    <div className="panel-heading"><div><h2>Patient clinical context</h2><p>Recorded view through {minuteLabel(minute)} after admission. No live hospital connection.</p></div><span className="info-chip">Research demonstration</span></div>
    {error && <p role="alert" className="form-error">{error} <button type="button" onClick={() => setRevision((value) => value + 1)}>Retry loading</button></p>}
    {message && <p role="status" className="form-success">{message}</p>}
    {!data && !error && <p role="status">Loading recorded observations and clinical context...</p>}
    {data && <>
      <div className="clinical-at-a-glance" aria-label="Patient context overview">
        <div><span>Responsible doctor</span><strong>{data.context?.physician_available ? data.context.physician_name : data.context?.physician_id ? 'Update assigned doctor' : 'Not selected'}</strong></div>
        <div><span>Assigned team</span><strong>{data.assignments.filter((person) => person.active && person.role === 'doctor').length} doctors · {data.assignments.filter((person) => person.active && person.role === 'nurse').length} nurses</strong></div>
        <div><span>Follow-ups to review</span><strong>{data.follow_ups.counts.pending} pending</strong></div>
      </div>
      <section className="clinical-block clinical-context-block" aria-labelledby="admission-context-title">
      <h3 id="admission-context-title">Admission and responsible doctor</h3><p className="panel-footnote">Admission details are not supplied by this dataset. Anything entered here is demonstration information, not an original patient fact or model input.</p>
      <dl className="model-info-list">{Object.entries(CONTEXT_FIELDS).map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{data.context?.[key] || 'Not provided'}</dd></div>)}<div><dt>Responsible physician</dt><dd>{data.context?.physician_name || 'Not selected'}{data.context?.physician_id && !data.context.physician_available && ' · No longer an active assigned doctor; update this selection.'}</dd></div></dl>
      {data.context && <p className="panel-footnote">Entered by {data.context.author} · recorded minute {minuteLabel(data.context.minute)} · saved {new Date(data.context.created_at * 1000).toLocaleString()}</p>}
      {canContext && <details className="clinical-disclosure"><summary>Edit admission / condition details</summary><form className="account-form clinical-form" key={`context-${data.context?.id || 0}`} onSubmit={(event) => {
        const values = new FormData(event.currentTarget)
        save(event, 'context', { ...Object.fromEntries(Object.keys(CONTEXT_FIELDS).map((key) => [key, values.get(key)])), minute: Number(values.get('minute')), physician_id: values.get('physician_id') ? Number(values.get('physician_id')) : null })
      }}>{timeInput}{Object.entries(CONTEXT_FIELDS).map(([key, label]) => <label key={key}>{label}<textarea name={key} rows={2} maxLength={['diagnosis'].includes(key) ? 300 : ['specialty', 'admission_severity'].includes(key) ? 100 : 2000} defaultValue={data.context?.[key] || ''} /></label>)}
        <label>Responsible physician<select name="physician_id" defaultValue={data.context?.physician_available ? data.context.physician_id : ''}><option value="">Not selected</option>{data.assignments.filter((person) => person.role === 'doctor' && person.active).map((person) => <option key={person.id} value={person.id}>{person.display_name}</option>)}</select></label><p className="panel-footnote">Choose from assigned doctors. Use the team section below to assign another doctor first. Saving appends a new revision.</p><button disabled={busy} className="action-button">Save context revision</button></form></details>}
      </section>
      <DoctorReviews data={data.review_requests} minute={minute} role={user.role} busy={busy} onSave={save} />
      <FollowUps data={data.follow_ups} minute={minute} canEdit={canNotes} busy={busy} onSave={save} />
      <section id="patient-vitals" className="clinical-block clinical-vitals-block">
      <h3>Blood pressure and vital summary</h3><p className="panel-footnote">Invasive and cuff readings remain separate. Values show their own observation times; missing readings are not filled in. A last recorded value may be old.</p>
      <div className="vital-grid">{data.vitals.slice(0, 6).map((series) => <VitalChart key={series.parameter} {...series} availableThroughMinutes={minute} />)}</div>
      <details className="clinical-disclosure"><summary>Other recorded vital signs and labs</summary><div className="vital-grid">{data.vitals.slice(6).map((series) => <VitalChart key={series.parameter} {...series} availableThroughMinutes={minute} />)}</div></details>
      </section>
      <div id="patient-warning-review" className="clinical-warning-columns"><section className="clinical-block">
      <h3>Vital-reading warnings · separate from model alerts</h3>
      <p className="panel-footnote">Doctor-entered demonstration limits only. No default clinical thresholds are supplied. These checks do not change mortality scores or model alert rules.</p>
      {data.rules.length === 0 ? <p>No vital warning limits configured. This does not mean the readings are normal.</p> : <ul className="clinical-warnings">{data.vital_warnings.map((item) => <li key={item.parameter} className={item.state === 'OUTSIDE_ENTERED_LIMITS' ? 'clinical-limit-warning' : ''}><strong>{VITAL_LABELS[item.parameter]}: {WARNING_LABELS[item.state]}</strong><span>Entered limits: {item.lower ?? 'no lower limit'} to {item.upper ?? 'no upper limit'}{item.latest && ` · last reading ${item.latest.value} at ${minuteLabel(item.latest.time_minutes)}`}</span></li>)}</ul>}
      {user.role === 'doctor' && <details className="clinical-disclosure"><summary>Edit demonstration warning limits</summary><form className="account-form clinical-form" key={`rules-${data.rule_history[0]?.id || 0}`} onSubmit={(event) => {
        const values = new FormData(event.currentTarget)
        const rules = Object.keys(VITAL_LABELS).map((parameter) => ({ parameter, lower: values.get(`${parameter}-lower`) === '' ? null : Number(values.get(`${parameter}-lower`)), upper: values.get(`${parameter}-upper`) === '' ? null : Number(values.get(`${parameter}-upper`)) })).filter((rule) => rule.lower !== null || rule.upper !== null)
        save(event, 'rules', { minute: Number(values.get('minute')), rules })
      }}>{timeInput}<p>Leave both limits blank to disable that measurement's warning. Limits apply from the recorded minute entered here.</p><div className="clinical-limit-grid">{Object.entries(VITAL_LABELS).map(([parameter, label]) => { const rule = data.rules.find((item) => item.parameter === parameter); return <fieldset key={parameter}><legend>{label}</legend><label>Lower limit<input type="number" min="0" step="any" name={`${parameter}-lower`} defaultValue={rule?.lower ?? ''} /></label><label>Upper limit<input type="number" min="0" step="any" name={`${parameter}-upper`} defaultValue={rule?.upper ?? ''} /></label></fieldset> })}</div><button disabled={busy} className="action-button">Save warning limits</button></form></details>}
      </section><section className="clinical-block"><h3>Model warning acknowledgement</h3><p className="panel-footnote">Acknowledgement means someone recorded seeing a model warning. It does not clear the warning or confirm treatment. Use the review-entry form below to acknowledge it.</p>
      <ul className="clinical-warnings">{patient.risk_trajectory.filter((point) => point.assessment_status !== 'NOT_YET_AVAILABLE').map((point) => { const ack = data.acknowledgements.find((item) => item.checkpoint === point.checkpoint && item.event_type === 'acknowledge'); return <li key={point.checkpoint}><strong>{point.checkpoint} · {point.alert_state?.replaceAll('_', ' ') || 'Not assessed'}</strong><span>{ack ? `Acknowledged by ${ack.author} · ${new Date(ack.created_at * 1000).toLocaleString()}` : point.alert_state && point.alert_state !== 'NO_ALERT' ? 'Not acknowledged' : 'No model warning to acknowledge'}</span></li> })}</ul>
      </section></div>
      {canNotes && <details className="clinical-disclosure"><summary>Add a visit, recommendation or follow-up</summary><form className="account-form clinical-form" onSubmit={(event) => { const values = new FormData(event.currentTarget); save(event, 'entries', { ...Object.fromEntries(['kind', 'assessment', 'plan', 'follow_up', 'escalation'].map((key) => [key, values.get(key)])), minute: Number(values.get('minute')), review_minute: values.get('review_minute') === '' ? null : Number(values.get('review_minute')) }) }}>
        <p>Staff-entered demonstration note. No treatment is generated or prescribed by the model.</p>{timeInput}<label>Entry type<select name="kind">{noteKinds.map((kind) => <option key={kind} value={kind}>{ENTRY_LABELS[kind]}</option>)}</select></label>
        <label>Assessment / visit summary<textarea name="assessment" required minLength={2} maxLength={2000} rows={3} /></label>
        <label>Staff-recorded plan or recommendation<textarea name="plan" maxLength={2000} rows={3} /></label><label>Follow-up actions<textarea name="follow_up" maxLength={2000} rows={2} /></label><label>Escalation criteria / request<textarea name="escalation" maxLength={2000} rows={2} /></label><label>Next review: minute after admission (optional)<input name="review_minute" type="number" min="0" max="1440" step="1" /></label><p className="panel-footnote">This form saves an escalation note only. Use Request doctor review above to send an in-app review request.</p><button disabled={busy} className="action-button">Save clinical entry</button>
      </form></details>}
      <h3 id="patient-timeline">Patient timeline</h3><label className="clinical-filter">Show<select value={timelineFilter} onChange={(event) => setTimelineFilter(event.target.value)}><option value="all">All events</option><option value="staff">Staff entries and acknowledgements</option><option value="recorded">Recorded readings and model assessments</option></select></label>
      <p className="panel-footnote">Newest recorded time first. Showing {Math.min(100, timeline.length)} of {timeline.length} loaded events. Note save dates are separate from time after admission.{data.history_truncated && ' Older saved entries were omitted; each record type is limited to 200 entries.'}</p>
      {timeline.length === 0 ? <p>No events in this recorded view.</p> : <ol className="review-history clinical-timeline">{timeline.slice(0, 100).map((item) => <li key={item.id}><strong>{minuteLabel(item.minute)} · {item.title}</strong><span>{item.source}{item.author && ` · ${item.author} · saved ${new Date(item.created_at * 1000).toLocaleString()}`}</span><p>{item.detail}</p>{item.plan && <p><b>Plan: </b>{item.plan}</p>}{item.follow_up && <p><b>Follow-up: </b>{item.follow_up}</p>}{item.escalation && <p><b>Escalation: </b>{item.escalation}</p>}{item.review_minute != null && <p>Next review: {minuteLabel(item.review_minute)} after admission · {'see Follow-ups for the tracked status'}</p>}</li>)}</ol>}
    </>}
  </section>
}
