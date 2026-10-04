import { useEffect, useState } from 'react'
import { useAuth } from '../context/Auth'
import { permissions, ROLE_LABELS } from '../permissions'
import { addPatientEvent, getStaff, getWorkflow } from '../services/accounts'
import PatientTeam from './PatientTeam'

const EVENT_LABELS = { review: 'Doctor review', observation: 'Observation note', acknowledge: 'Acknowledge warning', handover: 'Handover note' }

export default function PatientWorkflow({ patient, modelProfile }) {
  const { user } = useAuth()
  const access = permissions(user?.role)
  const [data, setData] = useState(null)
  const [staff, setStaff] = useState([])
  const [error, setError] = useState(null)
  const [message, setMessage] = useState(null)
  const [busy, setBusy] = useState(false)
  const [retry, setRetry] = useState(0)
  const readyPoints = patient.risk_trajectory.filter((point) => point.assessment_status === 'READY')
  useEffect(() => {
    if (!user) return undefined
    const controller = new AbortController()
    setData(null); setError(null)
    Promise.all([getWorkflow(patient.patient_id, modelProfile, patient.available_through_minutes, controller.signal), access.unit ? getStaff(controller.signal) : Promise.resolve([])])
      .then(([workflow, people]) => { if (!controller.signal.aborted) { setData(workflow); setStaff(people) } })
      .catch((failure) => { if (failure.name !== 'AbortError') setError(failure.message) })
    return () => controller.abort()
  }, [user?.id, patient.patient_id, modelProfile, patient.available_through_minutes, access.unit, retry])
  async function note(event) {
    event.preventDefault(); setBusy(true); setError(null); setMessage(null)
    const form = event.currentTarget
    const values = new FormData(form)
    try {
      await addPatientEvent(patient.patient_id, { model_profile: modelProfile, checkpoint: values.get('checkpoint'), event_type: values.get('event_type'), content: values.get('content') })
      form.reset(); setMessage('Your note has been saved.'); setRetry((value) => value + 1)
    } catch (failure) { setError(failure.message) }
    finally { setBusy(false) }
  }
  if (!user) return null
  return <section className="panel patient-workflow"><div className="panel-heading"><div><h2>Team and review history</h2><p>Notes refer to this model and its recorded checkpoints. They do not change readings, model scores, or alert states.</p></div></div>
    {error && <p role="alert" className="form-error">{error} <button type="button" onClick={() => setRetry((value) => value + 1)}>Retry</button></p>}
    {message && <p role="status" className="form-success">{message}</p>}
    {!data && !error && <p role="status">Loading patient team…</p>}
    {data && <>
      <PatientTeam key={patient.patient_id} patientId={patient.patient_id} assignments={data.assignments} staff={staff} canEdit={access.unit}
        onSaved={(assignments, text) => { setData((previous) => previous?.patient_id === patient.patient_id ? { ...previous, assignments } : previous); setMessage(text) }} />
      {access.events.length > 0 && readyPoints.length > 0 && <form className="account-form" onSubmit={note}>
        <h3>Add a review entry</h3><label>Entry type<select name="event_type" defaultValue={access.events[0]}>{access.events.map((type) => <option key={type} value={type}>{EVENT_LABELS[type]}</option>)}</select></label>
        <label>Assessment checkpoint<select name="checkpoint" defaultValue={readyPoints.some((point) => point.checkpoint === '12h') ? '12h' : readyPoints.at(-1).checkpoint}>{readyPoints.map((point) => <option key={point.checkpoint} value={point.checkpoint}>{point.checkpoint} · {point.alert_state.replaceAll('_', ' ')}</option>)}</select></label>
        <label>Your note<textarea name="content" required minLength={2} maxLength={2000} rows={3} /></label>
        <p className="panel-footnote">Acknowledgement records that someone saw a warning. It does not clear the warning or prove that care was given.</p>
        <button className="action-button" disabled={busy}>{busy ? 'Saving…' : 'Save review entry'}</button>
      </form>}
      <h3>Saved entries</h3>{data.events.length === 0 ? <p>No entries for the visible checkpoints of this model.</p> : <ol className="review-history">{data.events.map((item) => <li key={item.id}><strong>{EVENT_LABELS[item.event_type]} · {item.checkpoint}</strong><span>{item.author} · {ROLE_LABELS[item.actor_role]} · {new Date(item.created_at * 1000).toLocaleString()}</span><p>{item.content}</p><small>Recorded model score: {item.risk_score.toFixed(4)} · {item.alert_state.replaceAll('_', ' ')}</small></li>)}</ol>}
    </>}
  </section>
}
