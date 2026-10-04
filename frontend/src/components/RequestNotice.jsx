import { Link } from 'react-router-dom'
import { useRequestNotifications } from '../context/RequestNotifications'

export default function RequestNotice() {
  const { notice, pendingCount, dismiss } = useRequestNotifications()
  if (!notice) return null
  return <aside className="request-notice" role="alert" aria-label="New account request">
    <strong>New account request received</strong>
    <p>{pendingCount === null ? 'A worker requested access to the workspace.' : `You have ${pendingCount} pending account ${pendingCount === 1 ? 'request' : 'requests'}.`}</p>
    <div className="request-actions"><Link className="action-button" to="/requests" onClick={() => { dismiss(); window.dispatchEvent(new Event('silent-window-open-requests')) }}>View requests</Link>
      <button className="secondary-button" type="button" onClick={dismiss}>Dismiss</button></div>
  </aside>
}
