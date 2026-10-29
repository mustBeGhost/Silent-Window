import { createContext, useContext, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from './Auth'
import { requestJson } from '../services/api'
import { validateReviewSummary, unseenReviewKeys } from '../utils/doctorReviews'
import { isLiveConnected } from '../utils/liveStatus'
const Context = createContext({ count: 0, error: null })
export const useDoctorReviewNotifications = () => useContext(Context)
export function DoctorReviewNotificationProvider({ children }) {
  const { user } = useAuth()
  const owner = user ? `${user.id}:${user.role}` : ''
  const [state, setState] = useState({ owner: '', count: 0, error: null, notice: 0 })
  useEffect(() => {
    if (!user || !['admin', 'coordinator', 'doctor', 'nurse'].includes(user.role)) return undefined
    let stopped = false, controller = null
    const key = `silent-window-review-seen:${owner}`
    let seen = new Set()
    try { const ids = JSON.parse(sessionStorage.getItem(key) || '[]'); if (Array.isArray(ids)) seen = new Set(ids) } catch { /* Session storage can be disabled. */ }
    async function refresh() {
      if (document.hidden || controller) return
      controller = new AbortController()
      try {
        const data = await requestJson('/review-requests/summary', { signal: controller.signal })
        validateReviewSummary(data)
        if (!stopped) setState((old) => ({ owner, count: data.open_count, error: null, notice: user.role === 'doctor' ? unseenReviewKeys(data.pending_keys, seen).length : 0, ids: data.pending_keys }))
      } catch (error) { if (!stopped) setState((old) => ({ ...(old.owner === owner ? old : {count: 0, notice: 0}), owner, error: error.message })) }
      finally { controller = null }
    }
    const dismiss = () => setState((old) => {
      for (const id of old.ids || []) seen.add(id)
      try { sessionStorage.setItem(key, JSON.stringify([...seen].slice(-1000))) } catch { /* Optional persistence. */ }
      return { ...old, notice: 0 }
    })
    refresh()
    const timer = setInterval(() => { if (!isLiveConnected()) refresh() }, 30000)
    window.addEventListener('focus', refresh); document.addEventListener('visibilitychange', refresh)
    window.addEventListener('silent-window-reviews-changed', refresh); window.addEventListener('silent-window-reviews-dismiss', dismiss)
    return () => { stopped = true; controller?.abort(); clearInterval(timer); window.removeEventListener('focus', refresh); document.removeEventListener('visibilitychange', refresh); window.removeEventListener('silent-window-reviews-changed', refresh); window.removeEventListener('silent-window-reviews-dismiss', dismiss) }
  }, [owner])
  const current = state.owner === owner ? state : { count: 0, notice: 0, error: null }
  return <Context.Provider value={current}>{children}</Context.Provider>
}
export function DoctorReviewNotice() {
  const { notice } = useDoctorReviewNotifications()
  if (!notice) return null
  const dismiss = () => window.dispatchEvent(new Event('silent-window-reviews-dismiss'))
  return <aside className="request-notice" role="status" aria-label="Doctor review notification"><strong>{notice} pending doctor review {notice === 1 ? 'request' : 'requests'}</strong><p>Open the review inbox to see requests for your assigned patients.</p><div className="request-actions"><Link className="action-button" to="/review-requests" onClick={dismiss}>Open review requests</Link><button className="secondary-button" type="button" onClick={dismiss}>Dismiss review notification</button></div></aside>
}
