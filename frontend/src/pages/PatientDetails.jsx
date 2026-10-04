import { useEffect, useState, useSyncExternalStore } from 'react'
import { Link, useParams } from 'react-router-dom'

import AlertBadge from '../components/AlertBadge'
import AlertExplanation from '../components/AlertExplanation'
import RiskBadge from '../components/RiskBadge'
import RiskTrajectory from '../components/RiskTrajectory'
import VitalChart from '../components/VitalChart'
import { getPatientDetail, modelCheckpoints } from '../services/api'
import { assessmentLabel, formatScore } from '../utils/assessment'
import { useModelProfile } from '../context/ModelProfile'
import { RecordedReplay } from '../utils/replay'
import RecordedReplayControls from '../components/RecordedReplay'
import PatientWorkflow from '../components/PatientWorkflow'
import { useAuth } from '../context/Auth'

export default function PatientDetails() {
  const { modelProfile } = useModelProfile()
  const { patientId } = useParams()
  return <PatientSession key={`${modelProfile}:${patientId}`} patientId={patientId} modelProfile={modelProfile} />
}

function PatientSession({ patientId, modelProfile }) {
  const { user } = useAuth()
  const calibrated = modelProfile !== 'original'
  const checkpoints = modelCheckpoints(modelProfile)
  const [session] = useState(() => new RecordedReplay({
    initialStep: user?.preferences?.replay_step || 60,
    checkpoints: checkpoints.map((cp) => parseInt(cp, 10) * 60),
    load: (asOfMinutes, signal) => getPatientDetail(patientId, { signal, asOfMinutes, modelProfile }),
  }))
  const state = useSyncExternalStore(session.subscribe, session.getSnapshot, session.getSnapshot)
  const { patient, error } = state
  const controls = <details key="recorded-replay" className="replay-demo-disclosure"
    onToggle={(event) => { if (!event.currentTarget.open) session.pause() }}>
    <summary>Optional demo: replay recorded observations</summary>
    <RecordedReplayControls state={state} session={session} checkpoints={checkpoints} />
  </details>

  useEffect(() => {
    session.seek(1440)
    const pauseWhenHidden = () => { if (document.hidden && session.getSnapshot().playing) session.pause() }
    document.addEventListener('visibilitychange', pauseWhenHidden)
    return () => {
      document.removeEventListener('visibilitychange', pauseWhenHidden)
      session.pause({ abortLoading: true })
    }
  }, [session])

  if (!patient && !error) {
    return (
      <div className="page patient-page">
        {controls}
        <div className="state-panel patient-state-panel" role="status">
          <span className="loader" />
          <strong>Loading patient assessment...</strong>
          <span>Requesting this patient's detail only.</span>
        </div>
      </div>
    )
  }
  if (!patient && error) {
    const notFound = error?.status === 404
    const backendResponded = Number.isInteger(error?.status)
    return (
      <div className="page patient-page">
        {controls}
        <div className="state-panel patient-state-panel error-state" role="alert">
          <strong>{notFound ? 'Patient not found.' : 'Assessment unavailable.'}</strong>
          <span>
            {notFound
              ? 'No patient with this public ID is available.'
              : backendResponded
                ? 'Risk could not be calculated for this patient.'
                : 'Patient data could not be loaded. The backend may be unavailable.'}
          </span>
          {!notFound && <button onClick={() => session.retry()} type="button">Retry</button>}
          <Link to="/">Return to patient queue</Link>
        </div>
      </div>
    )
  }

  const viewHours = patient.available_through_minutes / 60

  return (
    <div className="page patient-page">
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <Link to="/">Back to patient queue</Link>
        <span aria-hidden="true">/</span>
        <strong>{patient.patient_id}</strong>
      </nav>

      {error && <div className="replay-error" role="alert">
        <p>The next recorded view could not be loaded. Playback stopped; the last received view is still shown.</p>
        <button type="button" onClick={() => session.retry()}>Retry recorded view</button>
      </div>}

      <section className="patient-identity panel">
        <div className="patient-avatar" aria-hidden="true">ICU</div>
        <div className="patient-identity-copy">
          <span className="section-kicker">Patient detail</span>
          <div className="patient-title-row">
            <h1>Patient {patient.patient_id}</h1>
            <span className="identity-chip">{patient.icu_type}</span>
            <span className="identity-chip">Primary checkpoint: {patient.primary_checkpoint}</span>
          </div>
          <p>Historical patient record viewed through hour {viewHours}. This is not a live hospital feed.</p>
        </div>
      </section>

      <section className={`risk-hero risk-hero-${patient.risk_level?.toLowerCase() || 'not_assessed'}`}>
        <div className="current-risk-block">
          <span className="section-kicker">Hospital-death risk model score (0–1)</span>
          <div className="hero-risk-value">{patient.assessment_status === 'READY' ? formatScore(patient.risk_probability) : assessmentLabel(patient.assessment_status)}</div>
          <span className="assessment-caption">Primary {patient.primary_checkpoint} assessment</span>
          {patient.assessment_reason && <p>{patient.assessment_reason}</p>}
        </div>
        <div className="assessment-summary" aria-label="Current assessment summary">
          <div className="assessment-item">
            <span>Risk category</span>
            <RiskBadge level={patient.risk_level} />
          </div>
          <div className="assessment-item">
            <span>Alert state</span>
            <AlertBadge state={patient.alert_state} />
          </div>
          <div className="assessment-item">
            <span>Score change from 6h to 12h</span>
            <strong className={`trend trend-${patient.risk_trend?.toLowerCase() || 'not_assessed'}`}>{patient.risk_trend || 'Not assessed'}</strong>
          </div>
        </div>
        <div className="decision-notice">
          <strong>About this assessment</strong>
          <p>The model was trained to predict death during the hospital stay. Its score is not a verified probability of death and does not predict when deterioration will happen. This is a research demonstration.</p>
        </div>
      </section>

      {controls}

      <PatientWorkflow key={patient.patient_id} patient={patient} modelProfile={modelProfile} />

      <div className="detail-grid">
        <RiskTrajectory points={patient.risk_trajectory} />
        <AlertExplanation checkpoints={patient.risk_trajectory} />

        <section className="panel vital-section">
          <div className="panel-heading">
            <div><h2>Clinical Observations</h2><p>Recorded measurements through hour {viewHours}. No measurements are added to fill gaps.</p></div>
            <span className="info-chip">Observed data</span>
          </div>
          <div className="vital-grid">
            {patient.vital_histories.map((series) => <VitalChart key={series.parameter} {...series} availableThroughMinutes={patient.available_through_minutes} />)}
          </div>
          <p className="panel-footnote">Charts use only timestamps and values returned by the patient-detail API.</p>
        </section>

        <section className="panel model-information-section">
          <div className="panel-heading">
            <div><h2>Model Information</h2><p>Transparent model context, not patient-specific feature attribution.</p></div>
            <span className="info-chip">No SHAP attribution</span>
          </div>
          <dl className="model-info-list">
            <div><dt>Model</dt><dd>{calibrated ? 'Random Forest with sigmoid calibration (research candidate)' : 'Original Random Forest'}</dd></div>
            <div><dt>Primary checkpoint</dt><dd>12h</dd></div>
            <div><dt>Trajectory checkpoints</dt><dd>{checkpoints.join(" / ")}</dd></div>
            <div><dt>Input categories</dt><dd>Demographics, vitals, labs, summary statistics, recency, and trend features</dd></div>
            <div><dt>Training outcome</dt><dd>Death during the hospital stay</dd></div>
            <div><dt>Output</dt><dd>{calibrated ? 'Calibrated research score from 0 to 1; individual clinical probability accuracy has not been established' : 'Model score from 0 to 1; probability calibration has not been established'}</dd></div>
          </dl>
          <div className="policy-note"><strong>How to interpret this view</strong><p>Observed measurements provide clinical context. They are not presented as patient-specific causes of the model output.</p></div>
        </section>
      </div>

      <footer className="information-footer"><strong>API inference at supported {checkpoints.join(" / ")} checkpoints.</strong><span>Primary assessment: 12h · {modelProfile === 'expanded' ? 'Five-checkpoint research candidate' : calibrated ? 'Calibrated research candidate' : 'Original Random Forest'}</span></footer>
    </div>
  )
}
