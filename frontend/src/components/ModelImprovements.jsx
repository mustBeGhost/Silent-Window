const percent = (value) => `${(value * 100).toFixed(1)}%`

export default function ModelImprovements({ report }) {
  const selected = report.training_selected.any_warning
  const families = [...new Set(report.selected_in_folds)].map((id) => report.candidates.find((candidate) => candidate.id === id)?.label ?? id)
  return (
    <section className="performance-panel model-improvements" aria-labelledby="improvements-title">
      <div className="performance-panel-heading">
        <div>
          <span className="section-kicker">New model and input comparison · 12h</span>
          <h2 id="improvements-title">Can a different model reduce extra warnings?</h2>
        </div>
        <span className="importance-chip">85% training detection target</span>
      </div>
      <p>We tested six fixed candidates on the same development patient groups. Recent inputs describe the last four hours, changes from earlier readings, and missing measurements. Each assessment uses only readings recorded by that time.</p>
      <p>Detection counts WATCH and HIGH ALERT together. These are validation results at the 12h assessment.</p>
      <p className="table-scroll-hint">Scroll sideways in the table to see missed cases and survivor warnings.</p>
      <div className="model-comparison-scroll">
        <table className="model-comparison-table">
          <caption>Model comparison at the 12h assessment</caption>
          <thead><tr><th scope="col">Candidate</th><th scope="col">Inputs</th><th scope="col">Death labels detected</th><th scope="col">Missed</th><th scope="col">Survivors warned</th><th scope="col">Ranking score</th></tr></thead>
          <tbody>
            {report.candidates.map((candidate) => (
              <tr key={candidate.id}>
                <th scope="row">{candidate.label}{candidate.id === 'rf_v2' && <small>Earlier 85% experiment reproduced</small>}</th>
                <td>{candidate.feature_count}</td>
                <td>{candidate.any_warning.tp} / {report.death_labels}<small>{percent(candidate.any_warning.recall_in_assessed_population)}</small></td>
                <td>{candidate.any_warning.fn}</td>
                <td>{candidate.any_warning.fp} / {candidate.any_warning.fp + candidate.any_warning.tn}</td>
                <td>{candidate.roc_auc.toFixed(3)}<small>ROC-AUC</small></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="training-choice-summary">
        <h3>Choosing the model using training patients only</h3>
        <p>In each training group, we chose the candidate with the fewest survivor warnings while meeting the 85% training target. We then tested that choice on the separate validation group.</p>
        <p><strong>{selected.tp} / {report.death_labels} detected ({percent(selected.recall_in_assessed_population)}), {selected.fn} missed, and {selected.fp} survivors warned.</strong></p>
        <p>Families chosen across the five training groups: {families.join('; ')}. This result describes the selection procedure; it is not an independently tested score for one model chosen after seeing all the results.</p>
        <p>Our research check required no fewer detected cases than the control and at least 10% fewer survivor warnings. <strong>{report.research_promotion_gate.passed ? 'The selection procedure met this check.' : 'The selection procedure did not meet both requirements.'}</strong> This is an engineering check, not a clinical safety standard.</p>
      </div>
      <div className="performance-explanation">
        <p>The ranking score describes separation across score thresholds. Higher values suggest better separation, but do not guarantee a useful warning setting. Compare detection and survivor warnings together; lower warning counts can also result from detecting fewer death labels.</p>
        <p><strong>The patient queue continues to use its existing saved models.</strong> These new comparisons are research results. The separate 640-patient cohort was excluded. This is not an untouched final test or evidence of hospital readiness.</p>
      </div>
    </section>
  )
}
