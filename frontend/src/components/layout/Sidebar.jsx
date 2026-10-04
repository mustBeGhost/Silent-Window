import { modelCheckpoints } from '../../services/api'
import { NavLink } from 'react-router-dom'
import { useModelProfile } from '../../context/ModelProfile'
import { useAuth } from '../../context/Auth'
import { permissions } from '../../permissions'
import { useRequestNotifications } from '../../context/RequestNotifications'

const navItems = [
  { label: 'Patient Queue', icon: '▰', to: '/' },
  { label: 'Model Performance', icon: '⌁', to: '/model-performance' },
]

export default function Sidebar() {
  const { user } = useAuth()
  const access = permissions(user?.role)
  const { pendingCount, error: requestCountError } = useRequestNotifications()
  const links = [...navItems.filter((item) => item.to !== '/' || !user || access.patients),
    { label: 'My Account', icon: '◌', to: '/account' },
    ...(access.accounts ? [{ label: 'Account Requests', icon: '✓', to: '/requests' }, { label: 'Team Accounts', icon: '▤', to: '/team' }] : [])]
  const { modelProfile } = useModelProfile()
  const calibrated = modelProfile !== 'original'
  const expanded = modelProfile === 'expanded'
  return (
    <aside className="sidebar">
      <div>
        <p className="sidebar-eyebrow">Navigation engine</p>
        <nav className="sidebar-nav" aria-label="Primary navigation">
          {links.map((item) => (
            <NavLink
              aria-label={item.label}
              title={item.label}
              className={({ isActive }) => (
                isActive ? 'nav-link active' : 'nav-link'
              )}
              end
              key={item.label}
              to={item.to}
            >
              <span aria-hidden="true">{item.icon}</span>
              <span>{item.label}</span>
              {item.to === '/requests' && pendingCount > 0 && <span className="request-count" aria-label={`${pendingCount} pending account requests`}>{pendingCount}</span>}
              {item.to === '/requests' && requestCountError && <span className="request-count" title={requestCountError} aria-label={requestCountError}>?</span>}
            </NavLink>
          ))}
        </nav>
      </div>

      <section className="engine-card" aria-label="Inference engine summary">
        <div className="engine-title">
          <span>Inference engine</span>
          <span>{expanded ? 'V4' : calibrated ? 'V3' : 'V2'}</span>
        </div>
        <dl>
          <div><dt>Model</dt><dd>{expanded ? 'Calibrated Random Forest V4' : calibrated ? 'Calibrated Random Forest V3' : 'Random Forest V2'}</dd></div>
          <div><dt>Checkpoints</dt><dd>{modelCheckpoints(modelProfile).join(" / ")}</dd></div>
          <div><dt>Primary</dt><dd>12h</dd></div>
          <div><dt>Data source</dt><dd>Historical patient observations</dd></div>
        </dl>
      </section>
    </aside>
  )
}
