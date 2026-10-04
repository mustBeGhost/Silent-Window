import { useState } from 'react'
import { getStaff, saveRoleAssignment } from '../services/accounts'

export function PatientTeamGroup({ role, assignments, staff, canEdit, patientId, onSaved }) {
  const plural = role === 'doctor' ? 'Doctors' : 'Nurses'
  const people = assignments.filter((person) => person.role === role)
  const [editing, setEditing] = useState(false)
  const [choices, setChoices] = useState(staff)
  const [selected, setSelected] = useState([])
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  async function edit() {
    setEditing(true); setBusy(true); setError(null); setSearch('')
    try {
      const latest = await getStaff()
      setChoices(latest)
      const eligible = new Set(latest.filter((person) => person.role === role).map((person) => person.id))
      setSelected(people.filter((person) => person.active && eligible.has(person.id)).map((person) => person.id))
    } catch (failure) { setError(failure.message) }
    finally { setBusy(false) }
  }
  async function save(event) {
    event.preventDefault(); setBusy(true); setError(null)
    try {
      const result = await saveRoleAssignment(patientId, role, selected)
      onSaved(result.assignments, `${plural} assigned to this patient have been updated.`)
      setEditing(false)
    } catch (failure) { setError(failure.message) }
    finally { setBusy(false) }
  }
  const eligible = choices.filter((person) => person.role === role)
  const visible = eligible.filter((person) => `${person.display_name} ${person.username || ''}`.toLowerCase().includes(search.toLowerCase()))
  return <details className="patient-team-group">
    <summary>{plural} <span className="team-count">{people.length}</span></summary>
    <div className="team-group-content">
      <h3>Assigned {plural.toLowerCase()}</h3>
      {people.length ? <ul className="assigned-staff">{people.map((person) => <li key={person.id}>
        <strong>{person.display_name}</strong> <span className="field-hint">{person.username ? `@${person.username}` : ''}{person.active ? '' : ' · Inactive account'}</span>
      </li>)}</ul> : <p>No {plural.toLowerCase()} assigned yet.</p>}
      {canEdit && !editing && <button type="button" className="secondary-button" onClick={edit}>Edit {plural.toLowerCase()}</button>}
      {canEdit && editing && <form className="account-form" onSubmit={save}>
        <label>Search {plural.toLowerCase()}<input type="search" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
        <fieldset disabled={busy || Boolean(error)}><legend>Select {plural.toLowerCase()}</legend>
          {visible.map((person) => <label className="inline-check" key={person.id}>
            <input type="checkbox" checked={selected.includes(person.id)} disabled={!selected.includes(person.id) && selected.length >= 20}
              onChange={(event) => setSelected((ids) => event.target.checked ? [...ids, person.id] : ids.filter((id) => id !== person.id))} />
            {person.display_name} <span className="field-hint">{person.username ? `@${person.username}` : ''}</span>
          </label>)}
          {!visible.length && <p>{eligible.length ? 'No matching staff. Try a different search.' : `No active ${plural.toLowerCase()} available. An administrator must approve the appropriate accounts first.`}</p>}
        </fieldset>
        <span className="field-hint">{selected.length} selected · Up to 20 per group. Saving only changes this patient's {plural.toLowerCase()}.</span>
        {busy && <p role="status">Please wait…</p>}
        {error && <p role="alert" className="form-error">{error} <button type="button" className="secondary-button" onClick={edit} disabled={busy}>Reload staff</button></p>}
        <div className="request-actions"><button className="action-button" disabled={busy || Boolean(error)}>Save {plural.toLowerCase()}</button>
          <button type="button" className="secondary-button" disabled={busy} onClick={() => { setEditing(false); setError(null) }}>Cancel</button></div>
      </form>}
    </div>
  </details>
}

export default function PatientTeam(props) {
  return <div className="patient-team-groups"><PatientTeamGroup role="doctor" {...props} /><PatientTeamGroup role="nurse" {...props} /></div>
}
