import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { Component, lazy, Suspense } from 'react'

import Header from './components/layout/Header'
import Sidebar from './components/layout/Sidebar'
import ModelNotice from './components/ModelNotice'
import { ModelProfileProvider, useModelProfile } from './context/ModelProfile'
import { AuthProvider, useAuth } from './context/Auth'
import { permissions } from './permissions'
import Login from './pages/Login'
import { RequestNotificationProvider } from './context/RequestNotifications'
import RequestNotice from './components/RequestNotice'
const Dashboard = lazy(() => import('./pages/Dashboard'))
const ModelPerformance = lazy(() => import('./pages/ModelPerformance'))
const PatientDetails = lazy(() => import('./pages/PatientDetails'))
const Account = lazy(() => import('./pages/Account'))
const TeamAccounts = lazy(() => import('./pages/TeamAccounts'))
const Register = lazy(() => import('./pages/Register'))
const PermissionRequests = lazy(() => import('./pages/PermissionRequests'))
const Recover = lazy(() => import('./pages/Recover'))

function PageLoading() {
  return <div className="page page-loading" role="status" aria-live="polite">Opening page…</div>
}

class PageBoundary extends Component {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() {
    if (this.state.failed) return <section className="page" role="alert"><h1>This page could not open</h1><p>Check your connection, then reload the page.</p><button className="action-button" onClick={() => window.location.reload()}>Reload page</button></section>
    return this.props.children
  }
}

function PageContent({ children }) {
  const { pathname } = useLocation()
  return <PageBoundary key={pathname}><Suspense fallback={<PageLoading />}>{children}</Suspense></PageBoundary>
}

export default function App() {
  return <AuthProvider><RequestNotificationProvider><SignedWorkspace /></RequestNotificationProvider></AuthProvider>
}

function SignedWorkspace() {
  const { user, loading, setupRequired, error } = useAuth()
  if (user) return <ModelProfileProvider key={`${user.id}:${user.role}`}><ModelWorkspace /></ModelProfileProvider>
  if (loading || setupRequired || error) return <Login />
  return <PageContent><Routes><Route path="/register" element={<Register />} /><Route path="/recover" element={<Recover />} /><Route path="*" element={<Login />} /></Routes></PageContent>
}

function ModelWorkspace() {
  const { modelProfile } = useModelProfile()
  const { user } = useAuth()
  const access = permissions(user.role)
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <Header />
      <Sidebar />
      <RequestNotice />
      <main className="main-content" id="main-content" tabIndex={-1}>
        <ModelNotice />
        <PageContent>
        <Routes>
          <Route path="/" element={access.patients ? <Dashboard key={modelProfile} /> : <Navigate to="/model-performance" replace />} />
          <Route path="/patients/:patientId" element={access.patients ? <PatientDetails /> : <Navigate to="/model-performance" replace />} />
          <Route path="/model-performance" element={<ModelPerformance key={modelProfile} />} />
          <Route path="/account" element={<Account />} />
          <Route path="/team" element={access.accounts ? <TeamAccounts /> : <Navigate to="/account" replace />} />
          <Route path="/requests" element={access.accounts ? <PermissionRequests /> : <Navigate to="/account" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        </PageContent>
      </main>
    </div>
  )
}
