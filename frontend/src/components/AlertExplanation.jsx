import AlertBadge from './AlertBadge'
import RiskBadge from './RiskBadge'
import { assessmentLabel, formatScore } from '../utils/assessment'

const PRIMARY_CHECKPOINT = '12h'
const ELEVATED_LEVELS = new Set(['MEDIUM', 'HIGH'])

function alertReason(current, previous) {
  if (current.assessment_status !== 'READY') {
    return `${assessmentLabel(current.assessment_status)}. ${current.assessment_reason}`
  }
  if (current.alert_state === 'NO_ALERT') {
    return `No alert is active because the current ${current.checkpoint} model-estimated risk category is LOW.`
  }

  if (current.alert_state === 'HIGH_ALERT') {
    return `High alert is active because model-estimated risk was elevated at two consecutive supported checkpoints: ${previous.checkpoint} and ${current.checkpoint}.`
  }

  if (!previous) {
    return `Watch is active because elevated model-estimated risk was detected at the first supported checkpoint; there is no previous assessment to establish persistence.`
  }
  if (previous.assessment_status !== 'READY') {
    return `Watch is active at ${current.checkpoint}. The previous checkpoint was not assessed, so repeated elevated scores cannot be established.`
  }

  return `Watch is active because elevated model-estimated risk was detected at ${current.checkpoint}, but the previous ${previous.checkpoint} risk category was LOW.`
}

export default function AlertExplanation({ checkpoints }) {
  const currentIndex = checkpoints.findIndex(
    (item) => item.checkpoint === PRIMARY_CHECKPOINT,
  )
  const current = checkpoints[currentIndex]
  const previous = currentIndex > 0 ? checkpoints[currentIndex - 1] : null
  const supportingCheckpoints = previous ? [previous, current] : [current]
  const persistenceMet = previous
    && ELEVATED_LEVELS.has(previous.risk_level)
    && ELEVATED_LEVELS.has(current.risk_level)

  return (
    <section className="panel alert-explanation-panel">
      <div className="panel-heading alert-explanation-heading">
        <div>
          <h2>Why this alert?</h2>
          <p>These demonstration rules check repeated elevated scores. They have not been validated for clinical use.</p>
        </div>
        <AlertBadge state={current.alert_state} />
      </div>

      <div className={`alert-reason alert-reason-${current.alert_state?.toLowerCase() || 'not_assessed'}`}>
        <span className="section-kicker">Current {PRIMARY_CHECKPOINT} result</span>
        <strong>{alertReason(current, previous)}</strong>
        {current.alert_state === 'WATCH' && previous && (
          <p>HIGH ALERT requires both the current and immediately previous supported checkpoints to be MEDIUM or HIGH.</p>
        )}
        {current.alert_state === 'HIGH_ALERT' && persistenceMet && (
          <p>Two scores met the rule. This does not prove that the patient is getting worse.</p>
        )}
      </div>

      <div className="supporting-assessments">
        <span className="supporting-label">Assessments used for the primary alert</span>
        <div className="policy-checkpoint-flow">
          {supportingCheckpoints.map((item, index) => (
            <div className="policy-checkpoint-step" key={item.checkpoint}>
              <article className={item.checkpoint === PRIMARY_CHECKPOINT ? 'current' : ''}>
                <span>{item.checkpoint === PRIMARY_CHECKPOINT ? 'Current assessment' : 'Previous assessment'}</span>
                <div className="policy-checkpoint-value">
                  <strong>{item.checkpoint}</strong>
                  <b>{formatScore(item.risk_probability)}</b>
                </div>
                <RiskBadge level={item.risk_level} />
              </article>
              {index < supportingCheckpoints.length - 1 && <span className="policy-flow-arrow" aria-hidden="true">-&gt;</span>}
            </div>
          ))}
          <div className="policy-result">
            <span>Result</span>
            <AlertBadge state={current.alert_state} />
          </div>
        </div>
      </div>

      <div className="policy-distinction" aria-label="Risk category and alert state distinction">
        <div>
          <strong>Risk category</strong>
          <p>LOW, MEDIUM, or HIGH from the model-estimated risk at one checkpoint.</p>
        </div>
        <div>
          <strong>Alert state</strong>
          <p>NO ALERT, WATCH, or HIGH ALERT after also checking persistence across supported checkpoints.</p>
        </div>
      </div>

      <p className="panel-footnote alert-policy-footnote">The current primary result uses {previous?.checkpoint || "the first checkpoint"} and {current.checkpoint} assessments. Later assessments remain visible in the trajectory.</p>
    </section>
  )
}
