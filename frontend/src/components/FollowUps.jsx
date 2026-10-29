import { useState } from 'react'
import { minuteLabel } from '../utils/clinical'

export default function FollowUps({ data, minute, canEdit, busy, onSave }) {
  const [filter, setFilter] = useState('pending')
  const items = data.items.filter((item) => filter === 'all' || item.status === filter)
  return <section id="patient-follow-ups" className="clinical-block follow-up-panel" aria-labelledby="follow-up-title">
    <div className="panel-heading"><div><span className="section-kicker">Review tracking</span><h3 id="follow-up-title">Follow-ups</h3><p>Staff-recorded actions. Completion does not clear a model alert or confirm a clinical outcome.</p></div>
      <label>Follow-up status<select value={filter} onChange={(event) => setFilter(event.target.value)}><option value="pending">Pending</option><option value="completed">Completed</option><option value="all">All follow-ups</option></select></label></div>
    <div className="follow-up-counts"><span><strong>{data.counts.pending}</strong> pending</span><span><strong>{data.counts.overdue}</strong> past the planned review time</span><span><strong>{data.counts.completed}</strong> completed</span></div>
    {data.truncated && <p className="panel-footnote">Showing up to 200 follow-ups, pending first. Counts include all follow-ups in this recorded view. Status history is limited to the latest 200 changes.</p>}
    {items.length === 0 ? <div className="clinical-empty">No {filter === 'all' ? '' : filter + ' '}follow-ups in the loaded list. Add follow-up actions or a next-review time in a clinical entry below.</div> : <div className="follow-up-list">{items.map((item) => <article key={`${item.entry_id}:${item.event_id}`} className="follow-up-card">
      <div className="follow-up-card-heading"><strong>{item.follow_up || item.assessment}</strong><span className={`follow-up-status follow-up-${item.status}`}>{item.status === 'completed' ? 'Completed' : item.review_minute != null && item.review_minute <= minute ? 'Pending · review due' : 'Pending'}</span></div>
      <p className="panel-footnote">Entry #{item.entry_id} · planned by {item.author} at {minuteLabel(item.minute)} after admission · next review: {item.review_minute == null ? 'not scheduled' : minuteLabel(item.review_minute)}</p>
      {item.status_author && <div className="follow-up-audit"><strong>{item.status === 'completed' ? 'Completed' : 'Reopened'} by {item.status_author}</strong><span>Recorded time: {minuteLabel(item.status_minute)} after admission · saved {new Date(item.status_saved_at * 1000).toLocaleString()}</span><p>{item.status_note}</p></div>}
      {canEdit && <details className="clinical-disclosure"><summary>{item.status === 'pending' ? 'Mark completed' : 'Reopen follow-up'}</summary><form className="account-form" onSubmit={(event) => {
        const values = new FormData(event.currentTarget)
        onSave(event, `entries/${item.entry_id}/follow-up`, { status: item.status === 'pending' ? 'completed' : 'pending', expected_event_id: item.event_id, minute: Number(values.get('minute')), content: values.get('content') })
      }}><label>Status change: recorded minute after admission<input name="minute" type="number" min={Math.max(item.minute, item.status_minute || 0)} max={minute} step="1" defaultValue={minute} required /></label><label>{item.status === 'pending' ? 'What was completed?' : 'Reason for reopening'}<textarea name="content" rows={2} required minLength={2} maxLength={2000} /></label><button className="action-button" disabled={busy}>{busy ? 'Saving…' : item.status === 'pending' ? 'Save completion' : 'Save as pending'}</button></form></details>}
    </article>)}</div>}
  </section>
}
