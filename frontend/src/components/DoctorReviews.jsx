import { minuteLabel } from '../utils/clinical'

export default function DoctorReviews({ data, minute, role, busy, onSave }) {
  const canRequest = ['doctor', 'nurse', 'coordinator'].includes(role)
  const time = <label>Recorded minute after admission<input name="minute" type="number" min="0" max={minute} step="1" defaultValue={minute} required /></label>
  return <section id="patient-review-requests" className="clinical-block">
    <h3>Doctor review requests</h3><p>Staff requests are separate from model alerts. Notifications appear inside this website while it is open; they do not confirm treatment.</p>
    <p>{data.counts.pending} pending · {data.counts.acknowledged} acknowledged · {data.counts.resolved} resolved</p>
    {data.counts.unassigned > 0 && <p role="status">{data.counts.unassigned} open requests have no active assigned doctor. Ask a coordinator to assign a doctor.</p>}
    {canRequest && <details className="clinical-disclosure"><summary>Request doctor review</summary><form className="account-form clinical-form" onSubmit={(event) => {
      const values = new FormData(event.currentTarget)
      onSave(event, 'review-requests', { minute: Number(values.get('minute')), reason: values.get('reason'), context: values.get('context') })
    }}>{time}<label>Reason for requesting review<textarea name="reason" required minLength={2} maxLength={2000} rows={3} /></label><label>Additional context (optional)<textarea name="context" maxLength={2000} rows={2} /></label><button className="action-button" disabled={busy}>Save doctor review request</button></form></details>}
    {data.items.length === 0 && <p>No doctor review requests in this recorded view.</p>}
    {data.items.map((item) => <article className="clinical-block" key={`${item.request_id}-${item.event_id}`}>
      <h4>Request #{item.request_id} · {item.status}</h4><p>{item.reason}</p>{item.context && <p>{item.context}</p>}
      <p className="panel-footnote">Requested by {item.author} at recorded {minuteLabel(item.minute)} · saved {new Date(item.created_at * 1000).toLocaleString()}</p>
      {item.status_author && <p>{item.status_author}: {item.status_note} · recorded {minuteLabel(item.status_minute)} · saved {new Date(item.status_saved_at * 1000).toLocaleString()}</p>}
      {item.assigned_doctor_count === 0 && item.status !== 'resolved' && <p>Waiting for an active doctor assignment.</p>}
      {canRequest && (item.status === 'resolved' || (role === 'doctor' && item.status !== 'resolved')) && <form className="account-form clinical-form" onSubmit={(event) => {
        const values = new FormData(event.currentTarget)
        onSave(event, `review-requests/${item.request_id}/status`, { minute: Number(values.get('minute')), expected_event_id: item.event_id, status: item.status === 'resolved' ? 'pending' : item.status === 'pending' ? 'acknowledged' : 'resolved', content: values.get('content') })
      }}>{time}<label>Action note<textarea name="content" required minLength={2} maxLength={2000} rows={2} /></label><button disabled={busy} className="action-button">{item.status === 'resolved' ? 'Reopen request' : item.status === 'pending' ? 'Acknowledge request' : 'Resolve request'}</button></form>}
    </article>)}
    {data.truncated && <p>Only the latest 200 requests and status changes are loaded. Counts include all requests.</p>}
  </section>
}
