export default function StatCard({ eyebrow, label, value, tone, note, icon }) {
  return (
    <article className={`stat-card tone-${tone}`}>
      <div className="stat-card-heading">
        <div>
          <p>{eyebrow}</p>
          <h2>{label}</h2>
        </div>
        <span className="stat-icon" aria-hidden="true">{icon}</span>
      </div>
      <div className="stat-card-value">{String(value).padStart(2, '0')}</div>
      <div className="stat-card-note">{note}</div>
    </article>
  )
}
