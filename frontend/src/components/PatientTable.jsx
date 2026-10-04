import { Link } from 'react-router-dom'

import AlertBadge from './AlertBadge'
import RiskBadge from './RiskBadge'
import { assessmentLabel, formatScore } from '../utils/assessment'

function Trend({ value }) {
  if (value == null) return <span>Not assessed</span>
  const lower = value.toLowerCase()
  const symbol = lower === 'rising' ? '↗' : lower === 'falling' ? '↘' : '→'
  return <span className={`trend trend-${lower}`}>{symbol} {value}</span>
}

export default function PatientTable({ patients }) {
  return (
    <div className="table-scroll">
      <table className="patient-table">
        <thead>
          <tr>
            <th>Patient ID</th>
            <th>ICU Type</th>
            <th>Checkpoint</th>
            <th>Model Score (0–1)</th>
            <th>Risk Level</th>
            <th>Alert State</th>
            <th>Score Change</th>
            <th><span className="sr-only">View patient</span></th>
          </tr>
        </thead>
        <tbody>
          {patients.map((patient) => {
            const percentage = patient.risk_probability == null ? 0 : patient.risk_probability * 100
            return (
              <tr className={`patient-row row-${patient.risk_level?.toLowerCase() || 'not_assessed'}`} key={patient.patient_id}>
                <td><strong className="patient-id">{patient.patient_id}</strong></td>
                <td><strong>{patient.icu_type}</strong></td>
                <td><span className="checkpoint">◷ {patient.checkpoint}</span></td>
                <td>
                  <div className="probability-cell">
                    <strong>{patient.assessment_status === 'READY' ? formatScore(patient.risk_probability) : assessmentLabel(patient.assessment_status)}</strong>
                    {patient.risk_probability != null && <span className="probability-track">
                      <span style={{ width: `${percentage}%` }} />
                    </span>}
                  </div>
                </td>
                <td><RiskBadge level={patient.risk_level} /></td>
                <td><AlertBadge state={patient.alert_state} /></td>
                <td><Trend value={patient.risk_trend} /></td>
                <td>
                  <Link className="view-button" state={{ patient }} to={`/patients/${encodeURIComponent(patient.patient_id)}`}>
                    View Patient <span aria-hidden="true">→</span>
                  </Link>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
