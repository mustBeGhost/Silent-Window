import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import AlertBadge from './AlertBadge'
import RiskBadge from './RiskBadge'
import { assessmentLabel, formatScore } from '../utils/assessment'

const CHECKPOINT_WINDOWS = {
  '6h': 'Uses observations from ICU admission through the 6h cutoff.',
  '9h': 'Uses observations from ICU admission through the 9h cutoff.',
  '18h': 'Uses observations from ICU admission through the 18h cutoff.',
  '12h': 'Uses observations from ICU admission through the 12h cutoff.',
  '24h': 'Uses observations from ICU admission through the 24h cutoff.',
}

function RiskTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      <span>{label} checkpoint</span>
      <strong>{formatScore(payload[0].value)} model score</strong>
    </div>
  )
}

export default function RiskTrajectory({ points }) {
  return (
    <section className="panel risk-trajectory-panel">
      <div className="panel-heading">
        <div>
          <div className="title-with-chip">
            <h2>Risk Trajectory</h2>
            <span className="info-chip">Discrete checkpoints only</span>
          </div>
          <p>Hospital-death risk scores at {points.length} assessment times. These times are not prediction horizons.</p>
        </div>
        <span className="info-chip">6h to 24h</span>
      </div>

      <div className="chronology-notice">
        <div className="chronology-origin" aria-hidden="true">
          <strong>0h</strong>
          <span>ICU admission</span>
        </div>
        <p><strong>Checkpoint-safe assessments</strong> Each assessment uses only information available up to and including that checkpoint. Later measurements are not used for earlier assessments.</p>
      </div>

      <ol className="trajectory-checkpoints" aria-label="Risk checkpoint summary">
        {points.map((point, index) => (
          <li className={point.checkpoint === '12h' ? 'primary' : ''} key={point.checkpoint}>
            <div className="trajectory-checkpoint-heading">
              <strong>{point.checkpoint}</strong>
              {point.checkpoint === '12h' && <span>Primary</span>}
            </div>
            <span className="trajectory-assessment-label">{point.checkpoint} risk assessment</span>
            <span className="trajectory-probability">{point.assessment_status === 'READY' ? formatScore(point.risk_probability) : assessmentLabel(point.assessment_status)}</span>
            <div className="trajectory-checkpoint-badges">
              <RiskBadge level={point.risk_level} />
              <AlertBadge state={point.alert_state} />
            </div>
            <p className="trajectory-window">{CHECKPOINT_WINDOWS[point.checkpoint]}</p>
            <p className="trajectory-window">{point.assessment_reason || `${point.temporal_observation_count} usable vital/lab observations. This count alone does not establish reliability.`}</p>
            {index < points.length - 1 && <span className="trajectory-arrow" aria-hidden="true">-&gt;</span>}
          </li>
        ))}
      </ol>

      <div className="risk-chart" aria-label={`Risk at ${points.map((point) => point.checkpoint).join(", ")} checkpoints`}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 18, right: 22, left: -12, bottom: 2 }}>
            <CartesianGrid stroke="#263044" strokeDasharray="3 5" vertical={false} />
            <XAxis dataKey="checkpoint" stroke="#8390a3" tickLine={false} axisLine={false} />
            <YAxis domain={[0, 1]} stroke="#8390a3" tickLine={false} axisLine={false} tickFormatter={(value) => value.toFixed(1)} />
            <Tooltip content={<RiskTooltip />} />
            <ReferenceLine x="12h" stroke="#7bd0ff" strokeDasharray="6 5" label={{ value: 'Primary', fill: '#7bd0ff', position: 'insideTopRight', fontSize: 11 }} />
            <Line dataKey="risk_probability" type="linear" connectNulls={false} stroke="#8ed5ff" strokeWidth={0} dot={{ r: 5, fill: '#0f131c', strokeWidth: 3 }} activeDot={{ r: 6 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="panel-footnote">Each dot is a separate checkpoint score. Missing assessments have no score. Scores are not verified probabilities of death; there are no continuous hourly predictions.</p>
    </section>
  )
}
