import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/Auth'
import { ROLE_LABELS } from '../permissions'
import { listAccounts, updateAccount } from '../services/accounts'
import AccountRecovery from '../components/AccountRecovery'

function AccessRow({ account, currentId, onSaved }) {
  const [role, setRole] = useState(account.role)
  const [active, setActive] = useState(account.active)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  async function save() {
    setBusy(true); setError(null)
    try { const updated = await updateAccount(account.id, { role, active }); onSaved(updated) }
    catch (failure) { setError(failure.message) }
    finally { setBusy(false) }
  }
  const self = currentId === account.id
  return <article className="account-access-row">
    <div><strong>{account.display_name}</strong><p>{account.username}{self ? ' · You' : ''}</p></div>
    <label>Role for {account.username}<select value={role} disabled={self || busy} onChange={(event) => setRole(event.target.value)}>{Object.entries(ROLE_LABELS).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
    <label className="inline-check"><input type="checkbox" checked={active} disabled={self || busy} onChange={(event) => setActive(event.target.checked)} />Active account</label>
    <button className="action-button" onClick={save} disabled={self || busy || (role === account.role && active === account.active)}>Save access</button>
    {error && <p role="alert" className="form-error">{error}</p>}
    <AccountRecovery account={account} currentId={currentId} />
  </article>
}

export default function TeamAccounts() {
  const { user } = useAuth()
  const [accounts, setAccounts] = useState([])
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState(null)
  const [message, setMessage] = useState(null)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setError(null); setLoaded(false)
    listAccounts(controller.signal).then((data) => { setAccounts(data); setLoaded(true) }).catch((failure) => { if (failure.name !== 'AbortError') setError(failure.message) })
    return () => controller.abort()
  }, [retry])
  function saved(account) { setAccounts((items) => items.map((item) => item.id === account.id ? account : item)); setMessage('Account access updated. Previous sessions for that account have ended.') }
  return <div className="page account-page"><div className="page-heading"><div><span className="section-kicker">Administrator</span><h1>Team accounts</h1><p>Manage approved accounts and choose what each person can do.</p></div></div>
    {error && <div className="form-error" role="alert">{error}{!loaded && <button onClick={() => setRetry((value) => value + 1)}>Retry loading accounts</button>}</div>}
    {message && <p className="form-success" role="status">{message}</p>}
    <section className="panel account-panel"><h2>Workers request their own accounts</h2><p>Workers use the request form on the sign-in page. Verify and approve them in <Link to="/requests">Account Requests</Link>. Pending and rejected requests do not appear as users.</p></section>
    <section className="panel account-panel"><h2>Manage access</h2><p className="panel-footnote">Disabling an account or changing its role ends its existing sessions. Your own administrator access is protected.</p>
      {!loaded && !error && <p role="status">Loading team accounts…</p>}
      {accounts.map((account) => <AccessRow key={account.id} account={account} currentId={user.id} onSaved={saved} />)}
    </section></div>
}
