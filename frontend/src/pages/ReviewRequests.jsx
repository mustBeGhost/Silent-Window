import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { requestJson } from '../services/api'
import { minuteLabel } from '../utils/clinical'
export default function ReviewRequests() {
  const [status, setStatus] = useState('open'), [offset, setOffset] = useState(0), [revision, setRevision] = useState(0)
  const [data, setData] = useState(null), [error, setError] = useState(null)
  useEffect(() => { const refresh = () => setRevision(value => value + 1); window.addEventListener('silent-window-workspace-refresh', refresh); return () => window.removeEventListener('silent-window-workspace-refresh', refresh) }, [])
  useEffect(() => {
    const controller = new AbortController(); setData(null); setError(null)
    requestJson(`/review-requests?status=${status}&offset=${offset}&limit=25`, { signal: controller.signal }).then((value) => { if (!controller.signal.aborted) setData(value) }).catch((failure) => { if (!controller.signal.aborted) setError(failure.message) })
    return () => controller.abort()
  }, [status, offset, revision])
  return <section className="page"><h1>Doctor review requests</h1><p>Requests through recorded hour 24, for patients you can access. Earlier patient replay views can show an earlier status.</p>
    <label>Request status<select value={status} onChange={(event) => { setStatus(event.target.value); setOffset(0) }}>{['open', 'pending', 'acknowledged', 'resolved', 'all'].map((value) => <option key={value} value={value}>{value}</option>)}</select></label><button type="button" onClick={() => setRevision((value) => value + 1)}>Refresh review requests</button>
    {error && <p role="alert">{error}</p>}{!data && !error && <p role="status">Loading requests…</p>}
    {data && <><p>{data.counts.pending} pending · {data.counts.acknowledged} acknowledged · {data.counts.resolved} resolved · {data.counts.unassigned} open without a doctor</p>
      {data.items.length === 0 && <p>No matching requests.</p>}
      {data.items.map((item) => <article className="panel" key={item.request_id}><h2>{item.patient_id} · Request #{item.request_id}</h2><p><strong>{item.status}</strong> · {item.reason}</p><p>Requested by {item.author} at recorded {minuteLabel(item.minute)} · saved {new Date(item.created_at * 1000).toLocaleString()}</p>{item.assigned_doctor_count === 0 && item.status !== 'resolved' && <p>Waiting for a doctor assignment.</p>}<Link to={`/patients/${encodeURIComponent(item.patient_id)}#patient-review-requests`}>Open patient and review request</Link></article>)}
      <p>{data.total} matching requests</p><button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous requests</button><button disabled={offset + 25 >= data.total} onClick={() => setOffset(offset + 25)}>Next requests</button></>}
  </section>
}
