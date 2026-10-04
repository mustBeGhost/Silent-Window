import { createContext, useContext, useEffect, useState } from 'react'
import { authStatus, currentSession, signIn, signOut, savePreferences } from '../services/accounts'
import { setRequestCsrfToken } from '../services/api'

export const AuthContext = createContext({ user: null, loading: true })
export const useAuth = () => useContext(AuthContext)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [setupRequired, setSetupRequired] = useState(false)
  const [error, setError] = useState(null)
  const [retry, setRetry] = useState(0)
  const [notice, setNotice] = useState(null)
  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false
    setLoading(true); setError(null)
    async function restore() {
      try {
        const status = await authStatus(controller.signal)
        if (cancelled) return
        setSetupRequired(status.setup_required)
        if (!status.setup_required) {
          try {
            const session = await currentSession(controller.signal)
            if (!cancelled) { setRequestCsrfToken(session.csrf_token); setUser(session.user) }
          } catch (failure) { if (failure.status !== 401) throw failure }
        }
      } catch (failure) { if (!cancelled && failure.name !== 'AbortError') setError(failure.message) }
      finally { if (!cancelled) setLoading(false) }
    }
    restore()
    return () => { cancelled = true; controller.abort() }
  }, [retry])
  useEffect(() => {
    const ended = () => { setRequestCsrfToken(null); setUser(null) }
    window.addEventListener('silent-window-session-ended', ended)
    return () => window.removeEventListener('silent-window-session-ended', ended)
  }, [])
  async function login(body) {
    const session = await signIn(body, setupRequired)
    setRequestCsrfToken(session.csrf_token); setUser(session.user); setSetupRequired(false); setNotice(null)
  }
  async function logout() {
    await signOut()
    setRequestCsrfToken(null); setUser(null)
  }
  async function updatePreferences(body) { const updated = await savePreferences(body); setUser(updated); return updated }
  function passwordChanged() {
    setRequestCsrfToken(null); setUser(null)
    setNotice('Your password was changed. Sign in again with your new password.')
  }
  return <AuthContext.Provider value={{ user, loading, setupRequired, error, notice, login, logout, updatePreferences, passwordChanged, retry: () => setRetry((value) => value + 1) }}>{children}</AuthContext.Provider>
}
