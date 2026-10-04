const percent = (value) => `${(value * 100).toFixed(1)}%`

export default function CheckpointExpansion({ report }) {
  const checkpoints = Object.keys(report.supported_cutoffs)
  const finalControl = report.control.cumulative_through_checkpoint['24h'].any_warning_seen
  const finalExpanded = report.expanded.cumulative_through_checkpoint['24h'].any_warning_seen
  return (
    <section className="performance-panel" aria-labelledby="checkpoint-expansion-title">
      <div className="performance-panel-heading">
        <div><span className="section-kicker">New checkpoint experiment · same calibrated Random Forest</span>
          <h2 id="checkpoint-expansion-title">What do 9h and 18h add?</h2></div>
        <span className="info-chip">6h / 9h / 12h / 18h / 24h</span>
      </div>
      <p>We compared three and five assessment times using the same patient folds, model settings, and training-selected warning thresholds. The training target was 85% detection at 12h. It is not a guarantee at every time.</p>
      <p><strong>By 24h, five checkpoints warned on {finalExpanded.tp} death-labelled patients versus {finalControl.tp} with three checkpoints.</strong> They also warned on {finalExpanded.fp - finalControl.fp} more survivor-labelled patients ({finalExpanded.fp} versus {finalControl.fp}). This small gain does not establish better overall accuracy.</p>
      <div className="checkpoint-report-scroll">
        <table className="checkpoint-report-table">
          <caption>Results at each assessment time, not predictions of when death happens</caption>
          <thead><tr><th>Assessment</th><th>Death labels warned now</th><th>Survivors warned now</th><th>Death labels warned at least once so far</th><th>Survivors warned at least once so far</th><th>Not assessed now</th></tr></thead>
          <tbody>{checkpoints.map((cp) => {
            const now = report.expanded.checkpoints[cp].any_warning
            const cumulative = report.expanded.cumulative_through_checkpoint[cp].any_warning_seen
            return <tr key={cp}><th scope="row">{cp}</th><td>{now.tp} / {now.tp + now.fn} ({percent(now.recall_in_assessed_population)})</td><td>{now.fp}</td><td>{cumulative.tp} / {report.death_labels}</td><td>{cumulative.fp}</td><td>{now.unassessed_patients}</td></tr>
          })}</tbody>
        </table>
      </div>
      <div className="performance-explanation">
        <p>Warnings include WATCH and HIGH ALERT. Each patient is counted once in the “at least once” columns. HIGH ALERT requires two consecutive elevated assessments; with five checkpoints, the 12h alert checks 9h and 12h.</p>
        <p><strong>The five-checkpoint model is a separate research option in the model selector.</strong> Its final thresholds were selected using development training patients. These results describe the evaluation procedure, not an independent test of the final saved models. The original and V3 models retain their settings.</p>
        <p>{report.development_patients.toLocaleString()} development patients; {report.death_labels} death labels. {report.validation_method}. The separate 640-patient cohort stayed out of fitting and evaluation. Exact death and ICU exit times are unknown, so these results cannot establish warning time before death or clinical readiness.</p>
      </div>
    </section>
  )
}
