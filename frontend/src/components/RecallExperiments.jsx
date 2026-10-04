import { useState } from 'react'
import { useModelProfile } from '../context/ModelProfile'

const percent = (value) => `${(value * 100).toFixed(1)}%`

export default function RecallExperiments({ report }) {
  const { modelProfile } = useModelProfile()
  const [comparison, setComparison] = useState(modelProfile !== 'original' ? 'calibrated' : 'raw')
  const rows = report.models[comparison]
  return (
    <section className="performance-panel recall-experiments" aria-labelledby="recall-title">
      <div className="performance-panel-heading">
        <div>
          <span className="section-kicker">New development experiments · 12h assessment</span>
          <h2 id="recall-title">Catch more cases: what does it cost?</h2>
        </div>
        <label className="recall-comparison">Comparison model
          <select value={comparison} onChange={(event) => setComparison(event.target.value)}>
            <option value="calibrated">Calibrated Random Forest</option>
            <option value="raw">Uncalibrated reference from the same fits</option>
          </select>
        </label>
      </div>
      <p>We aimed for 70%, 85%, and 90% detection using training patients. These results come from separate validation patients within the development data. A target is a goal; the measured result can differ.</p>
      <p><strong>Detection here means WATCH or HIGH ALERT at 12 hours.</strong> It is the share of death-labelled patients warned, not an individual patient&apos;s chance of death or overall accuracy.</p>
      <div className="recall-grid">
        {rows.map((row) => {
          const warning = row.any_warning
          const high = row.persistent_high_alert
          const totalWarnings = warning.tp + warning.fp
          return (
            <article className="recall-card" key={row.training_recall_target}>
              <h3>{Math.round(row.training_recall_target * 100)}% training target</h3>
              <strong className="recall-result">{percent(warning.recall_in_assessed_population)}</strong>
              <span>Measured detection at 12h</span>
              <dl>
                <div><dt>Death labels detected</dt><dd>{warning.tp} / {warning.tp + warning.fn}</dd></div>
                <div><dt>Death labels missed</dt><dd>{warning.fn}</dd></div>
                <div><dt>Survivors warned</dt><dd>{warning.fp} / {warning.fp + warning.tn}</dd></div>
                <div><dt>All patients warned</dt><dd>{totalWarnings} / {warning.assessed_patients} ({percent(totalWarnings / warning.assessed_patients)})</dd></div>
                <div><dt>Warnings with a death label</dt><dd>{percent(warning.precision)}</dd></div>
                <div><dt>Death labels with HIGH ALERT</dt><dd>{high.tp}</dd></div>
                <div><dt>Death labels with WATCH only</dt><dd>{warning.tp - high.tp}</dd></div>
                <div><dt>Survivors with HIGH ALERT</dt><dd>{high.fp}</dd></div>
                <div><dt>Survivors with WATCH only</dt><dd>{warning.fp - high.fp}</dd></div>
                <div><dt>Patients without an assessment</dt><dd>{warning.unassessed_patients}</dd></div>
              </dl>
            </article>
          )
        })}
      </div>
      <div className="performance-explanation">
        <p>HIGH ALERT requires elevated scores at consecutive checkpoints. WATCH is still a warning. Lowering the warning threshold can catch more death labels while also warning on more survivors.</p>
        <p>Survivor warnings count as false positives for the death target. The data does not tell us whether those patients needed clinical attention.</p>
        <p><strong>These earlier comparisons used three checkpoints. The original and V3 queues keep their earlier settings; the separate five-checkpoint candidate now uses its own training-selected 85% target.</strong> The queue keeps the boundaries shown above in the model notice.</p>
        <p>{report.development_patients.toLocaleString()} development patients; {report.death_labels} death labels. {report.validation_method}. Threshold selection and calibration use training patients only. The separate 640-patient cohort was excluded. This is not an untouched final test or a clinical validation.</p>
      </div>
    </section>
  )
}
