import { useId, useState } from 'react'
import { USERNAME_HINT, usernameError } from '../utils/accountValidation'

export function UsernameField({ label = 'Username', existingUsernames = [], error: serverError, onChange, autoComplete = 'username' }) {
  const id = useId()
  const [value, setValue] = useState('')
  const [touched, setTouched] = useState(false)
  const validationError = usernameError(value, existingUsernames)
  const duplicate = value && existingUsernames.some((name) => name.toLowerCase() === value.toLowerCase())
  const error = serverError || ((touched || duplicate) && validationError)
  function validate(input) { input.setCustomValidity(usernameError(input.value, existingUsernames) || '') }
  return <div className="account-field">
    <label htmlFor={id}>{label}</label>
    <input id={id} name="username" required minLength={3} maxLength={32} pattern="[a-z][a-z0-9]{2,31}"
      value={value} autoComplete={autoComplete} autoCapitalize="none" spellCheck={false}
      aria-invalid={error ? true : undefined} aria-describedby={`${id}-hint${error ? ` ${id}-error` : ''}`}
      onChange={(event) => { setValue(event.target.value); validate(event.target); onChange?.() }}
      onBlur={(event) => { setTouched(true); validate(event.target) }}
      onInvalid={(event) => { setTouched(true); validate(event.target) }} />
    <span id={`${id}-hint`} className="field-hint">{USERNAME_HINT}</span>
    {error && <span id={`${id}-error`} className="field-error" role="alert">{error}</span>}
  </div>
}

export function PasswordField({ label, name, minLength = 15, autoComplete = 'new-password' }) {
  const id = useId()
  const [visible, setVisible] = useState(false)
  return <div className="account-field">
    <label htmlFor={id}>{label}</label>
    <div className="password-input">
      <input id={id} name={name} type={visible ? 'text' : 'password'} required minLength={minLength} maxLength={128} autoComplete={autoComplete} />
      <button type="button" className="password-toggle" aria-label={`${visible ? 'Hide' : 'Show'} ${label.toLowerCase()}`}
        aria-controls={id} aria-pressed={visible} onClick={() => setVisible((shown) => !shown)}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" />
          {visible && <path d="m3 3 18 18" />}
        </svg>
      </button>
    </div>
  </div>
}
