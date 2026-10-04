import { useModelProfile } from '../context/ModelProfile'

export default function ModelNotice() {
  const { modelProfile, options, optionsState } = useModelProfile()
  const option = options.find((entry) => entry.id === modelProfile)
  const calibrated = modelProfile !== 'original'
  const expanded = modelProfile === 'expanded'
  return (
    <aside className={`model-notice ${calibrated ? 'model-notice-candidate' : ''}`} aria-label="Selected model version">
      <strong>{expanded ? 'Five-checkpoint research candidate' : calibrated ? 'Calibrated research candidate' : 'Original Random Forest'}</strong>
      <p>{expanded
        ? "Adds 9h and 18h assessments with an 85% training recall target. More recorded warnings also mean more survivor warnings. Scores are not verified clinical probabilities; this is not a proven accuracy improvement."
        : calibrated
        ? 'Calibration adjusts the score scale. Development testing showed no clear improvement in warning accuracy. Scores are not verified clinical probabilities.'
        : 'Historical model and thresholds. Scores are not calibrated probabilities. This is a research demonstration.'}</p>
      {option?.available && <span>Risk boundaries: medium {option.medium_threshold.toFixed(2)} · high {option.high_threshold.toFixed(2)}. A high alert still requires two elevated checkpoints.</span>}
      {optionsState === 'error' && <span role="status">Model version details could not be loaded. Reload the page to try again.</span>}
    </aside>
  )
}
