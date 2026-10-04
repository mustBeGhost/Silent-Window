import { useState } from 'react'
import { useAuth } from '../context/Auth'
import { changePassword } from '../services/accounts'
import { PasswordField } from './AccountFields'

export default function ChangePassword() {
  const { passwordChanged } = useAuth()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  async function submit(event) {
    event.preventDefault(); setError(null)
    const values = new FormData(event.currentTarget)
    if (values.get('new_password') !== values.get('confirmation')) { setError('The passwords do not match.'); return }
    setBusy(true)
    try {
      await changePassword({ current_password: values.get('current_password'), new_password: values.get('new_password') })
      passwordChanged()
    } catch (failure) { setError(failure.message) }
    finally { setBusy(false) }
  }
  return <section className="panel account-panel"><h2>Change password</h2>
    <p>Use at least 15 characters. Changing your password signs you out on all devices.</p>
    <form className="account-form" onSubmit={submit}>
      <fieldset disabled={busy} className="password-fields">
        <PasswordField label="Current password" name="current_password" minLength={1} autoComplete="current-password" />
        <PasswordField label="New password" name="new_password" />
        <PasswordField label="Confirm new password" name="confirmation" />
      </fieldset>
      {error && <p role="alert" className="form-error">{error}</p>}
      <button className="action-button" disabled={busy}>{busy ? 'Changing password…' : 'Change password'}</button>
    </form></section>
}
