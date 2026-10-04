import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/Auth'
import { PasswordField, UsernameField } from '../components/AccountFields'
import { usernameError } from '../utils/accountValidation'

export default function Login() {
  const auth = useAuth()
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError(null)
    const form = new FormData(event.currentTarget)
    const body = { username: form.get('username'), password: form.get('password') }
    if (auth.setupRequired) {
      const invalidUsername = usernameError(body.username)
      if (invalidUsername) { setError(invalidUsername); setBusy(false); return }
      if (body.password !== form.get('confirmation')) { setError('The passwords do not match.'); setBusy(false); return }
      body.display_name = form.get('display_name')
    }
    try { await auth.login(body) } catch (failure) { setError(failure.message) }
    finally { setBusy(false) }
  }
  return <main className="auth-page">
    <section className="auth-card panel">
      <span className="section-kicker">Silent Window · ICU outcome research</span>
      <h1>{auth.loading ? 'Opening your workspace…' : auth.setupRequired ? 'Set up your workspace' : 'Welcome back'}</h1>
      <p>{auth.setupRequired ? 'Create the first administrator account on this laptop. You can then add your team and assign their roles.' : 'Sign in to open your research workspace.'}</p>
      {auth.notice && <p role="status" className="form-success">{auth.notice}</p>}
      {auth.error ? <div role="alert"><p>{auth.error}</p><button className="action-button" onClick={auth.retry}>Retry connection</button></div>
        : !auth.loading && <form className="account-form" onSubmit={submit}>
          {auth.setupRequired && <label>Your name<input name="display_name" required minLength={2} maxLength={60} autoComplete="name" /></label>}
          {auth.setupRequired ? <UsernameField /> : <label>Username<input name="username" required minLength={3} maxLength={32} pattern="[A-Za-z0-9_.-]+" autoComplete="username" autoCapitalize="none" /></label>}
          <PasswordField label="Password" name="password" minLength={auth.setupRequired ? 15 : 1} autoComplete={auth.setupRequired ? 'new-password' : 'current-password'} />
          {auth.setupRequired && <><p className="panel-footnote">Use a password or passphrase with at least 15 characters.</p><PasswordField label="Confirm password" name="confirmation" /></>}
          {error && <p role="alert" className="form-error">{error}</p>}
          <button className="action-button" disabled={busy}>{busy ? 'Please wait…' : auth.setupRequired ? 'Create administrator account' : 'Sign in'}</button>
        </form>}
      {!auth.loading && !auth.error && !auth.setupRequired && <p>Need access? <Link to="/register">Request an account</Link></p>}
      {!auth.loading && !auth.error && !auth.setupRequired && <p><Link to="/recover">Forgot your password?</Link></p>}
      <p className="panel-footnote">Recorded ICU data and experimental model results. This is a research demonstration.</p>
    </section>
  </main>
}
