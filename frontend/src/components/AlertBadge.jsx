const labels = {
  NO_ALERT: 'No Alert',
  WATCH: 'Watch',
  HIGH_ALERT: 'High Alert',
  NOT_ASSESSED: 'Not assessed',
}

export default function AlertBadge({ state }) {
  const normalized = String(state || 'NOT_ASSESSED').toUpperCase()
  return (
    <span className={`alert-badge alert-${normalized.toLowerCase()}`}>
      <span className="badge-dot" />
      {labels[normalized] || normalized}
    </span>
  )
}
