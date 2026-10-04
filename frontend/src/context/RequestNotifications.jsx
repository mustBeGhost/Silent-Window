import { createContext, useContext, useEffect, useRef, useState } from 'react'
import { useAuth } from './Auth'
import { getRequestSummary } from '../services/accounts'
import { RequestNotifications } from '../utils/requestNotifications'

const empty = { pendingCount: null, notice: null, error: null }
export const RequestNotificationContext = createContext({ ...empty, dismiss: () => {}, refresh: () => {} })
export const useRequestNotifications = () => useContext(RequestNotificationContext)

export function RequestNotificationProvider({ children }) {
  const { user } = useAuth()
  const [state, setState] = useState(empty)
  const controller = useRef(null)
  useEffect(() => {
    setState(empty)
    if (user?.role !== 'admin') return undefined
    const key = `silent-window-request-seen:${user.id}`
    let seenId = 0
    try { seenId = Number(sessionStorage.getItem(key)) || 0 } catch { /* Use memory if browser storage is disabled. */ }
    const poller = new RequestNotifications({ load: getRequestSummary, seenId,
      onSeen: (value) => sessionStorage.setItem(key, String(value)), isVisible: () => !document.hidden })
    controller.current = poller
    const unsubscribe = poller.subscribe(() => setState(poller.getSnapshot()))
    const refresh = () => poller.refresh()
    const visible = () => { if (!document.hidden) refresh() }
    window.addEventListener('focus', refresh)
    window.addEventListener('silent-window-requests-changed', refresh)
    document.addEventListener('visibilitychange', visible)
    poller.start()
    return () => {
      unsubscribe(); poller.stop(); controller.current = null
      window.removeEventListener('focus', refresh)
      window.removeEventListener('silent-window-requests-changed', refresh)
      document.removeEventListener('visibilitychange', visible)
    }
  }, [user?.id, user?.role])
  const value = user?.role === 'admin' ? state : empty
  return <RequestNotificationContext.Provider value={{ ...value, dismiss: () => controller.current?.dismiss(), refresh: () => controller.current?.refresh() }}>{children}</RequestNotificationContext.Provider>
}
