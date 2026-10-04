import { useState } from 'react'
import { Link } from 'react-router-dom'
import { PasswordField } from '../components/AccountFields'
import { resetPassword } from '../services/accounts'

export default function Recover() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [message, setMessage] = useState(null)
  async function submit(event) {
    event.preventDefault(); setError(null)
    const values = new FormData(event.currentTarget)
    if (values.get('password') !== values.get('confirmation')) { setError('The passwords do not match.'); return }
    setBusy(true)
    try {
      const result = await resetPassword({ username: values.get('username'), recovery_code: values.get('recovery_code').trim(), password: values.get('password') })
      setMessage(result.message)
    } catch (failure) { setError(failure.message) }
    finally { setBusy(false) }
  }
  return <main className="auth-page"><section className="auth-card panel">
    <span className="section-kicker">Silent Window · Account recovery</span><h1>Choose a new password</h1>
    <p>Contact your workspace administrator to verify your identity and obtain a recovery code. Codes work once and expire after 15 minutes.</p>
    {message ? <p role="status" className="form-success">{message}</p> : <form className="account-form" onSubmit={submit}>
      <fieldset disabled={busy} className="password-fields">
        <label>Username<input name="username" required minLength={3} maxLength={32} pattern="[A-Za-z0-9_.-]+" autoCapitalize="none" autoComplete="username" /></label>
        <label>Recovery code<input name="recovery_code" required minLength={43} maxLength={43} autoCapitalize="none" autoComplete="off" spellCheck={false} /></label>
        <PasswordField label="New password" name="password" />
        <PasswordField label="Confirm new password" name="confirmation" />
      </fieldset>
      {error && <p role="alert" className="form-error">{error}</p>}
      <button className="action-button" disabled={busy}>{busy ? 'Resetting password…' : 'Reset password'}</button>
    </form>}
    <p><Link to="/">Back to sign in</Link></p>
    <p className="panel-footnote">If no administrator can sign in, the person managing the MySQL server can use the documented local recovery procedure.</p>
  </section></main>
}
