import { createContext, useContext, useEffect, useState } from 'react'
import { useAuth } from './Auth'
import { API_BASE_URL } from '../services/api'
import { WorkspaceEvents } from '../utils/workspaceEvents'
import { setLiveConnected } from '../utils/liveStatus'
const Context = createContext(false)
export const useWorkspaceLive = () => useContext(Context)
export function WorkspaceLiveProvider({ children }) {
  const { user } = useAuth()
  const [connected, setConnected] = useState(false)
  useEffect(() => {
    if (!user || user.role === 'researcher') return undefined
    const stream = new WorkspaceEvents({url:`${API_BASE_URL}/workspace/events`,
      onConnected:value=>{setConnected(value);setLiveConnected(value)},
      onRefresh:()=>{for(const name of ['silent-window-workspace-refresh','silent-window-workflow-changed','silent-window-reviews-changed','silent-window-requests-changed'])window.dispatchEvent(new Event(name))},
      onSessionEnded:()=>window.dispatchEvent(new Event('silent-window-session-ended'))})
    const open=()=>stream.open(!document.hidden)
    open();document.addEventListener('visibilitychange',open)
    return()=>{stream.close();document.removeEventListener('visibilitychange',open)}
  }, [user?.id,user?.role])
  return <Context.Provider value={connected}>{children}</Context.Provider>
}
