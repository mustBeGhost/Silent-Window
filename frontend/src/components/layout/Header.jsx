import { modelCheckpoints } from '../../services/api'
import { Link } from 'react-router-dom'
import { useModelProfile } from '../../context/ModelProfile'
import { useAuth } from '../../context/Auth'
import { ROLE_LABELS } from '../../permissions'
import { useState } from 'react'

export default function Header() {
  const { user, logout } = useAuth()
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  async function signOut() {
    setBusy(true); setError(null)
    try { await logout() } catch (failure) { setError(failure.message) }
    finally { setBusy(false) }
  }
  const { modelProfile, setModelProfile, options, optionsState } = useModelProfile()
  const candidateAvailable = options.some((option) => option.id === 'calibrated' && option.available)
  const expandedAvailable = options.some((option) => option.id === 'expanded' && option.available)
  return (
    <header className="top-header">
      <Link className="brand" to="/" aria-label="Silent Window dashboard">
        <span className="brand-mark" aria-hidden="true">⌁</span>
        <span className="brand-name">Silent Window</span>
        <span className="product-tag">ICU Outcome Research</span>
      </Link>

      <div className="header-context model-context" aria-label="Model context">
        <label className="model-picker">
          Model version
          <select value={modelProfile} onChange={(event) => setModelProfile(event.target.value)} disabled={optionsState !== 'ready'}>
            <option value="original">Original Random Forest</option>
            <option value="calibrated" disabled={!candidateAvailable}>Calibrated research candidate{optionsState === 'ready' && !candidateAvailable ? ' (unavailable)' : ''}</option>
            <option value="expanded" disabled={!expandedAvailable}>Five-checkpoint research candidate{optionsState === "ready" && !expandedAvailable ? " (unavailable)" : ""}</option>
          </select>
        </label>
        <span className="pipeline-status">
          Checkpoints: {modelCheckpoints(modelProfile).join(" / ")}
        </span>
      </div>

      <div className="header-actions" aria-label="Assessment context">
        <span className="header-fact">
          <span>Primary assessment</span>
          <strong>12h</strong>
        </span>
        {!user && <span className="header-fact">
          <span>Cohort</span>
          <strong>Full available cohort</strong>
        </span>}
        {user && <><Link className="header-fact user-identity" to="/account" title={`${user.display_name} · ${ROLE_LABELS[user.role]}`}><span>{ROLE_LABELS[user.role]}</span><strong>{user.display_name}</strong></Link><button className="signout-button" type="button" onClick={signOut} disabled={busy}>{busy ? 'Signing out…' : 'Sign out'}</button></>}
        {error && <span className="header-error" role="alert">{error}</span>}
      </div>
    </header>
  )
}
