import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ROLE_LABELS } from '../permissions'
import { PasswordField, UsernameField } from '../components/AccountFields'
import { usernameError } from '../utils/accountValidation'
import { requestAccount } from '../services/accounts'

export default function Register() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [usernameFailure, setUsernameFailure] = useState(null)
  const [submitted, setSubmitted] = useState(false)
  async function submit(event) {
    event.preventDefault(); setError(null); setUsernameFailure(null)
    const values = new FormData(event.currentTarget)
    const invalid = usernameError(values.get('username'))
    if (invalid) { setUsernameFailure(invalid); return }
    if (values.get('password') !== values.get('confirmation')) { setError('The passwords do not match.'); return }
    setBusy(true)
    try {
      await requestAccount({ username: values.get('username'), display_name: values.get('display_name'),
        password: values.get('password'), requested_role: values.get('requested_role'), request_note: values.get('request_note') })
      setSubmitted(true)
    } catch (failure) {
      if (failure.status === 409 && /username/.test(failure.message)) setUsernameFailure(failure.message)
      else setError(failure.message)
    } finally { setBusy(false) }
  }
  return <main className="auth-page"><section className="auth-card panel">
    <span className="section-kicker">Silent Window · Team access</span>
    <h1>{submitted ? 'Request submitted' : 'Request an account'}</h1>
    {submitted ? <p role="status">Your request is waiting for administrator approval. You cannot sign in yet. After approval, use the username and password you chose. Contact your administrator to check the decision.</p>
      : <><p>Choose your requested role. An administrator must verify and approve your request before you can sign in.</p>
        <form className="account-form" onSubmit={submit}>
          <label>Your name<input name="display_name" required minLength={2} maxLength={60} autoComplete="name" /></label>
          <UsernameField error={usernameFailure} onChange={() => setUsernameFailure(null)} />
          <label>Requested role<select name="requested_role" required defaultValue="">
            <option value="" disabled>Choose your role</option>
            {Object.entries(ROLE_LABELS).filter(([role]) => role !== 'admin').map(([role, label]) => <option value={role} key={role}>{label}</option>)}
          </select></label>
          <label>Staff details for verification (optional)<textarea name="request_note" maxLength={500} rows={3} /></label>
          <span className="field-hint">You can include your staff ID or department. Do not include patient information.</span>
          <PasswordField label="Password" name="password" />
          <span className="field-hint">Use at least 15 characters.</span>
          <PasswordField label="Confirm password" name="confirmation" />
          {error && <p role="alert" className="form-error">{error}</p>}
          <button className="action-button" disabled={busy}>{busy ? 'Submitting…' : 'Submit account request'}</button>
        </form></>}
    <p><Link to="/">Back to sign in</Link></p>
  </section></main>
}
