import { useEffect, useRef, useState } from 'react'
import { PasswordField } from './AccountFields'
import { issueRecovery } from '../services/accounts'

export default function AccountRecovery({ account, currentId }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const generation = useRef(0)
  useEffect(() => {
    generation.current += 1; setResult(null); setError(null); setOpen(false); setBusy(false)
    return () => { generation.current += 1 }
  }, [account.role, account.active])
  useEffect(() => {
    if (!result) return
    const timer = setTimeout(() => { setResult(null); setError('The code expired. Generate a new code if still needed.') },
      Math.max(0, result.expires_at * 1000 - Date.now()))
    return () => clearTimeout(timer)
  }, [result])
  async function submit(event) {
    event.preventDefault(); setBusy(true); setResult(null); setError(null)
    const current = ++generation.current
    const values = new FormData(event.currentTarget)
    try {
      const issued = await issueRecovery(account.id, { current_password: values.get('current_password') })
      if (current === generation.current) setResult(issued)
    }
    catch (failure) { if (current === generation.current) setError(failure.message) }
    finally { if (current === generation.current) setBusy(false) }
  }
  if (account.id === currentId || !account.active) return null
  return <div className="account-recovery">
    <button className="secondary-button" type="button" disabled={busy} aria-expanded={open}
      onClick={() => { setOpen((value) => !value); setResult(null); setError(null) }}>Password recovery for {account.username}</button>
    {open && <div className="recovery-content">
      <p>Verify this person's identity first. Give the code privately to the account owner so they can choose their own password at <strong>/recover</strong>.</p>
      {result ? <div role="status"><label>One-use recovery code for {account.username}<input value={result.recovery_code} readOnly autoComplete="off" spellCheck={false} /></label>
        <p>Expires {new Date(result.expires_at * 1000).toLocaleTimeString()}. Issuing another code replaces this one. The account password has not changed yet.</p>
        <button type="button" className="secondary-button" onClick={() => setResult(null)}>Clear code</button></div>
        : <form className="account-form" onSubmit={submit}>
          <fieldset disabled={busy} className="password-fields">
            <label className="inline-check"><input type="checkbox" required />I verified the account owner's identity.</label>
            <PasswordField label="Your administrator password" name="current_password" minLength={1} autoComplete="current-password" />
          </fieldset>
          <button className="action-button" disabled={busy}>{busy ? 'Creating code…' : 'Generate recovery code'}</button>
        </form>}
      {error && <p role="alert" className="form-error">{error}</p>}
    </div>}
  </div>
}
