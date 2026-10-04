const percent = (value) => `${(value * 100).toFixed(1)}%`

export default function ForestTuning({ report }) {
  const chosen = report.results.fine.training_selected.any_warning
  const reference = report.results.coarse.rf_v2.any_warning
  const fineReference = report.results.fine.rf_v2.any_warning
  const choices = [...new Set(report.selected_in_folds)].map((id) => report.candidate_definitions[id].label)
  return (
    <section className="performance-panel model-improvements" aria-labelledby="forest-tuning-title">
      <div className="performance-panel-heading">
        <div>
          <span className="section-kicker">Focused forest experiment · 12h</span>
          <h2 id="forest-tuning-title">Do smaller threshold steps help?</h2>
        </div>
        <span className="importance-chip">85% training detection target</span>
      </div>
      <p>We tested five fixed forest settings. Depth limits how many decisions a tree can make; leaf size sets the smallest training group at its end. Recent inputs describe the last four hours and changes in readings.</p>
      <p>For every model, the two threshold grids use the same predictions. The earlier grid checks scores in steps of 0.01; the finer grid uses 0.001. Smaller steps change when a warning starts. They do not improve the model’s ability to rank patients.</p>
      <div className="training-choice-summary">
        <h3>The choice made using training patients only</h3>
        <p><strong>{chosen.tp} / {report.death_labels} death labels detected ({percent(chosen.recall_in_assessed_population)}), {chosen.fn} missed, and {chosen.fp} survivors warned.</strong></p>
        <p>The earlier control detected {reference.tp} and warned on {reference.fp} survivors. With the finer grid, that same control detected {fineReference.tp} and warned on {fineReference.fp} survivors.</p>
        <p>Each training group chose a setting using the finer grid, before its separate validation group was tested. Settings chosen across the five groups: {choices.join('; ')}.</p>
        <p>The research check requires no fewer detected cases and at least 10% fewer survivor warnings against both control grids. <strong>{report.research_promotion_gate.passed ? 'The selection procedure met this check.' : 'The selection procedure did not meet all requirements.'}</strong> This is an engineering check, not a clinical safety standard.</p>
      </div>
      <p>Below are measured validation results. Detection counts warning eligibility at 12h (WATCH or HIGH ALERT), not HIGH ALERT alone. Later readings are excluded.</p>
      <p>{reference.assessed_patients} patients were assessed. {reference.unassessed_patients} had no usable readings and remain unassessed; {reference.unassessed_death_labels} of those have death labels. Missing data is not treated as low risk.</p>
      <p className="table-scroll-hint">Scroll sideways to compare both grids.</p>
      <div className="model-comparison-scroll">
        <table className="model-comparison-table">
          <caption>Same predictions, two training-selected threshold grids</caption>
          <thead><tr><th scope="col">Forest setting</th><th scope="col">Grid step</th><th scope="col">Death labels detected</th><th scope="col">Missed</th><th scope="col">Survivors warned</th></tr></thead>
          <tbody>
            {Object.entries(report.candidate_definitions).flatMap(([id, candidate]) => ['coarse', 'fine'].map((grid) => {
              const counts = report.results[grid][id].any_warning
              return <tr key={`${id}-${grid}`}>
                <th scope="row">{candidate.label}<small>{candidate.feature_count} inputs</small></th>
                <td>{grid === 'fine' ? '0.001' : '0.01'}</td>
                <td>{counts.tp} / {report.death_labels}<small>{percent(counts.recall_in_assessed_population)}</small></td>
                <td>{counts.fn}</td>
                <td>{counts.fp} / {counts.fp + counts.tn}</td>
              </tr>
            }))}
          </tbody>
        </table>
      </div>
      <div className="performance-explanation">
        <p><strong>The patient queue keeps its existing saved models and thresholds.</strong> These comparisons use known development data. The separate 640-patient cohort was excluded; this is not an untouched final test.</p>
        <p>Survivor warnings count against the death label. We do not know whether those patients needed medical attention. The 85% target is a training goal, not a guarantee. This study covers 12h warning eligibility; it does not validate repeated alerts or warning time before an event.</p>
      </div>
    </section>
  )
}
