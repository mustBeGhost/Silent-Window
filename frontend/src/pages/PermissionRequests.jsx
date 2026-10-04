import { useEffect, useState } from 'react'
import { ROLE_LABELS } from '../permissions'
import { listPermissionRequests, reviewPermissionRequest } from '../services/accounts'

export function ReviewedRequestRow({ request }) {
  return <article className="reviewed-request">
    <div className="reviewed-request-summary">
      <div><strong>{request.display_name}</strong><span className="field-hint">@{request.username}</span></div>
      <div><span className="field-hint">Requested role</span><span>{ROLE_LABELS[request.requested_role]}</span></div>
      <div><span className="field-hint">Granted role</span><span>{request.granted_role ? ROLE_LABELS[request.granted_role] : 'No account created'}</span></div>
      <div><span className={`request-status request-status-${request.status}`}>{request.status}</span><span className="field-hint">{request.reviewed_at ? new Date(request.reviewed_at * 1000).toLocaleString() : '—'}</span></div>
    </div>
    <details className="request-history-details"><summary>View details for {request.username}</summary>
      <p>Submitted {new Date(request.created_at * 1000).toLocaleString()}</p>
      <p>Reviewed by administrator account #{request.reviewed_by}</p>
      {request.request_note && <p className="request-note">Staff details: {request.request_note}</p>}
      <p className="request-note">Review note: {request.review_note || 'No note added.'}</p>
    </details>
  </article>
}

function RequestRow({ request, onReviewed }) {
  const [role, setRole] = useState(request.requested_role)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  async function review(decision) {
    setBusy(true); setError(null)
    try {
      await reviewPermissionRequest(request.id, { decision, ...(decision === 'approve' ? { role } : {}), note })
      onReviewed(`${request.username}: request ${decision === 'approve' ? 'approved' : 'rejected'}.`)
    } catch (failure) { setError(failure.message) }
    finally { setBusy(false) }
  }
  return <article className="permission-request">
    <h3>{request.display_name} <span className="field-hint">({request.username})</span></h3>
    <p>Requested role: <strong>{ROLE_LABELS[request.requested_role]}</strong></p>
    <p className="field-hint">Submitted {new Date(request.created_at * 1000).toLocaleString()}</p>
    {request.request_note && <p className="request-note">{request.request_note}</p>}
    {request.status === 'pending' ? <>
      <div className="account-form">
        <label>Role to grant for {request.username}<select value={role} disabled={busy} onChange={(event) => setRole(event.target.value)}>
          {Object.entries(ROLE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></label>
        {role === 'admin' && <span className="field-hint">Administrator access includes approving requests and managing every account.</span>}
        <label>Review note for {request.username} (optional)<textarea maxLength={500} value={note} disabled={busy} onChange={(event) => setNote(event.target.value)} rows={2} /></label>
      </div>
      <div className="request-actions"><button className="action-button" disabled={busy} onClick={() => review('approve')}>Approve {request.username}</button>
        <button className="reject-button" disabled={busy} onClick={() => review('reject')}>Reject {request.username}</button></div>
      {error && <p className="form-error" role="alert">{error}</p>}
    </> : <>
      <p>Status: <strong>{request.status}</strong>{request.granted_role ? ` · Granted role: ${ROLE_LABELS[request.granted_role]}` : ' · No account created'}</p>
      {request.reviewed_at && <p className="field-hint">Reviewed {new Date(request.reviewed_at * 1000).toLocaleString()}</p>}
      {request.review_note && <p className="request-note">Review note: {request.review_note}</p>}
    </>}
  </article>
}

export default function PermissionRequests() {
  const [status, setStatus] = useState('pending')
  const [offset, setOffset] = useState(0)
  const [data, setData] = useState({ items: [], total: 0 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [message, setMessage] = useState(null)
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    const openPending = () => { setStatus('pending'); setOffset(0); setMessage(null); setRevision((value) => value + 1) }
    window.addEventListener('silent-window-open-requests', openPending)
    return () => window.removeEventListener('silent-window-open-requests', openPending)
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError(null)
    listPermissionRequests(status, offset, controller.signal).then((result) => {
      if (controller.signal.aborted) return
      if (offset && offset >= result.total) { setOffset(Math.max(0, offset - 50)); return }
      setData(result)
    }).catch((failure) => { if (failure.name !== 'AbortError') setError(failure.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [status, offset, revision])
  function reviewed(text) { setMessage(text); setRevision((value) => value + 1) }
  return <div className="page account-page"><div className="page-heading"><div>
    <span className="section-kicker">Administrator</span><h1>Account requests</h1>
    <p>Verify the worker's identity and requested role before approving. Approval creates their account; rejection does not.</p>
  </div></div>
    <section className="panel account-panel">
      <div className="request-toolbar"><label>Request status <select value={status} onChange={(event) => { setStatus(event.target.value); setOffset(0); setMessage(null) }}>
        <option value="pending">Pending</option><option value="approved">Approved</option><option value="rejected">Rejected</option>
      </select></label><button className="action-button" disabled={loading} onClick={() => setRevision((value) => value + 1)}>Refresh requests</button></div>
      {message && <p className="form-success" role="status">{message}</p>}
      {error && <p className="form-error" role="alert">{error}</p>}
      {loading ? <p role="status">Loading requests…</p> : !error && <>
        <p>{data.total} {status} requests{data.total > 0 ? ` · Showing ${offset + 1}–${Math.min(offset + 50, data.total)}` : ''}</p>
        {data.items.map((request) => request.status === 'pending' ? <RequestRow key={request.id} request={request} onReviewed={reviewed} /> : <ReviewedRequestRow key={request.id} request={request} />)}
        {!data.items.length && <p>No {status} requests.</p>}
        <div className="request-actions"><button className="action-button" disabled={offset === 0} onClick={() => setOffset((value) => value - 50)}>Previous page</button>
          <button className="action-button" disabled={offset + 50 >= data.total} onClick={() => setOffset((value) => value + 50)}>Next page</button></div>
      </>}
    </section>
  </div>
}
