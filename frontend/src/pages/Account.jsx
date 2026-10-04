import { useState } from 'react'
import { useAuth } from '../context/Auth'
import { ROLE_LABELS } from '../permissions'
import ChangePassword from '../components/ChangePassword'

export default function Account() {
  const { user, updatePreferences } = useAuth()
  const [message, setMessage] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  async function save(event) {
    event.preventDefault(); setBusy(true); setMessage(null); setError(null)
    const values = new FormData(event.currentTarget)
    try {
      await updatePreferences({ display_name: values.get('display_name'), preferred_model: values.get('preferred_model'),
        page_size: Number(values.get('page_size')), replay_step: Number(values.get('replay_step')) })
      setMessage('Your preferences have been saved.')
    } catch (failure) { setError(failure.message) }
    finally { setBusy(false) }
  }
  return <div className="page account-page"><div className="page-heading"><div><span className="section-kicker">Your account</span><h1>Profile and security</h1><p>{user.username} · {ROLE_LABELS[user.role]}</p></div></div>
    <div className="account-settings-grid">
    <section className="panel account-panel"><h2>Make this workspace yours</h2><form className="account-form" onSubmit={save}>
      <label>Display name<input name="display_name" defaultValue={user.display_name} required minLength={2} maxLength={60} /></label>
      <label>Preferred model<select name="preferred_model" defaultValue={user.preferences.preferred_model}><option value="original">Original Random Forest</option><option value="calibrated">Calibrated research candidate</option><option value="expanded">Five-checkpoint research candidate</option></select></label>
      <label>Patients per page<select name="page_size" defaultValue={user.preferences.page_size}>{[25, 50, 100].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
      <label>Default replay speed<select name="replay_step" defaultValue={user.preferences.replay_step}><option value={15}>15 minutes per step</option><option value={60}>1 hour per step</option><option value={180}>3 hours per step</option></select></label>
      <p className="panel-footnote">Saved preferences apply to your account and remain after signing out. Replay preferences take effect when opening a patient.</p>
      {message && <p role="status" className="form-success">{message}</p>}{error && <p role="alert" className="form-error">{error}</p>}
      <button className="action-button" disabled={busy}>{busy ? 'Saving…' : 'Save preferences'}</button>
    </form></section><ChangePassword /></div></div>
}
