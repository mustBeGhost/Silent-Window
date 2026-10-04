export default function RiskBadge({ level }) {
  const normalized = String(level || 'NOT_ASSESSED').toUpperCase()
  if (level == null) return <span className="risk-badge risk-not_assessed">Not assessed</span>
  return <span className={`risk-badge risk-${normalized.toLowerCase()}`}>{normalized}</span>
}
