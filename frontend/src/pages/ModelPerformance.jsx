import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import performanceData from '../data/modelPerformance.json'
import recallReport from '../data/recallExperiments.json'
import improvementReport from '../data/modelImprovements.json'
import forestReport from '../data/forestTuning.json'
import ForestTuning from '../components/ForestTuning'
import CheckpointExpansion from '../components/CheckpointExpansion'
import checkpointReport from '../data/checkpointExpansion.json'
import ModelImprovements from '../components/ModelImprovements'
import RecallExperiments from '../components/RecallExperiments'
import { useModelProfile } from '../context/ModelProfile'

const CURVE_COLORS = {
  '6h': '#60a5fa',
  '12h': '#f59e0b',
  '24h': '#34d399',
}

const CHANCE_LINE = [
  { fpr: 0, tpr: 0 },
  { fpr: 1, tpr: 1 },
]

function formatRate(value) {
  return Number(value).toFixed(2)
}

function RocTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const point = payload[0].payload
  return (
    <div className="chart-tooltip">
      <strong>{payload[0].name}</strong>
      <span>False positive rate: {formatRate(point.fpr)}</span>
      <span>True positive rate: {formatRate(point.tpr)}</span>
    </div>
  )
}

function ImportanceTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const feature = payload[0].payload
  return (
    <div className="chart-tooltip">
      <strong>{feature.label}</strong>
      <span>Importance: {(feature.importance * 100).toFixed(2)}%</span>
      <small>{feature.technical_name}</small>
    </div>
  )
}

export default function ModelPerformance() {
  const { modelProfile } = useModelProfile()
  const { metadata, roc_curves: curves, feature_importance: importance } = performanceData

  return (
    <div className="page performance-page">
      <section className="page-heading performance-heading">
        <div>
          <span className="section-kicker">Model performance</span>
          <h1>Warning performance</h1>
          <p>Compare detection with the number of survivor warnings. The model target is death during the hospital stay.</p>
        </div>
        <dl className="performance-metadata" aria-label="Validation summary">
          <div><dt>Primary checkpoint</dt><dd>{metadata.primary_checkpoint}</dd></div>
          <div><dt>Validation method</dt><dd>{metadata.validation_method}</dd></div>
          <div><dt>Development cohort</dt><dd>{metadata.development_cohort_size.toLocaleString()} patients</dd></div>
        </dl>
      </section>

      <CheckpointExpansion report={checkpointReport} />
      <ForestTuning report={forestReport} />
      <ModelImprovements report={improvementReport} />
      <RecallExperiments report={recallReport} />
      <h2>Historical original-model charts</h2>
      <p className="panel-footnote">These historical charts describe the original Random Forest, {modelProfile !== 'original' ? 'while patient assessments currently use a calibrated research candidate. ' : 'which is currently selected for patient assessments. '}They predate the new missing-data guard and do not evaluate the research candidates or establish hospital readiness.</p>
      <section className="performance-panel" aria-labelledby="roc-title">
        <div className="performance-panel-heading">
          <div>
            <span className="section-kicker">Development 5-fold cross-validation</span>
            <h2 id="roc-title">ROC Curve</h2>
          </div>
          <div className="auc-summary" aria-label="ROC-AUC values">
            {curves.map((curve) => (
              <div key={curve.checkpoint}>
                <span style={{ color: CURVE_COLORS[curve.checkpoint] }}>{curve.label}</span>
                <strong>{curve.roc_auc.toFixed(4)}</strong>
                <small>ROC-AUC</small>
              </div>
            ))}
          </div>
        </div>

        <div className="performance-chart roc-chart" aria-label="ROC curves for 6h, 12h, and 24h Random Forest models">
          <ResponsiveContainer height="100%" width="100%">
            <LineChart margin={{ top: 16, right: 26, bottom: 32, left: 18 }}>
              <CartesianGrid stroke="#293345" strokeDasharray="3 4" />
              <XAxis
                dataKey="fpr"
                domain={[0, 1]}
                label={{ value: 'False Positive Rate', position: 'insideBottom', offset: -20 }}
                stroke="#8994a4"
                tickFormatter={formatRate}
                type="number"
              />
              <YAxis
                dataKey="tpr"
                domain={[0, 1]}
                label={{ value: 'True Positive Rate', angle: -90, position: 'insideLeft' }}
                stroke="#8994a4"
                tickFormatter={formatRate}
                type="number"
              />
              <Tooltip content={<RocTooltip />} />
              <Legend verticalAlign="top" />
              <Line
                data={CHANCE_LINE}
                dataKey="tpr"
                dot={false}
                isAnimationActive={false}
                name="Chance"
                stroke="#667386"
                strokeDasharray="6 6"
                strokeWidth={2}
                type="linear"
              />
              {curves.map((curve) => (
                <Line
                  activeDot={{ r: 4 }}
                  data={curve.points}
                  dataKey="tpr"
                  dot={false}
                  isAnimationActive={false}
                  key={curve.checkpoint}
                  name={`${curve.label} · AUC ${curve.roc_auc.toFixed(4)}`}
                  stroke={CURVE_COLORS[curve.checkpoint]}
                  strokeWidth={curve.primary ? 3 : 2}
                  type="stepAfter"
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="performance-explanation">
          <p>This curve shows how well the model separates higher-risk from lower-risk cases across different thresholds. Curves closer to the top-left indicate better discrimination.</p>
          <p><strong>12h is the primary checkpoint</strong> because the system aims to provide earlier warning while retaining useful predictive performance.</p>
        </div>
      </section>

      <section className="performance-panel" aria-labelledby="importance-title">
        <div className="performance-panel-heading">
          <div>
            <span className="section-kicker">Primary checkpoint: 12h</span>
            <h2 id="importance-title">Global Feature Importance — 12h</h2>
          </div>
          <span className="importance-chip">Top {importance.top_n} of {importance.transformed_feature_count} transformed inputs</span>
        </div>

        <div className="performance-chart importance-chart" aria-label="Top ten global Random Forest feature importances at 12h">
          <ResponsiveContainer height="100%" width="100%">
            <BarChart
              data={importance.features}
              layout="vertical"
              margin={{ top: 8, right: 30, bottom: 24, left: 22 }}
            >
              <CartesianGrid horizontal={false} stroke="#293345" strokeDasharray="3 4" />
              <XAxis
                domain={[0, 'dataMax']}
                label={{ value: 'Mean decrease in impurity', position: 'insideBottom', offset: -16 }}
                stroke="#8994a4"
                tickFormatter={(value) => `${(value * 100).toFixed(1)}%`}
                type="number"
              />
              <YAxis
                dataKey="label"
                stroke="#aeb7c5"
                tick={{ fontSize: 11 }}
                type="category"
                width={190}
              />
              <Tooltip content={<ImportanceTooltip />} />
              <Bar
                dataKey="importance"
                fill="#52bff5"
                isAnimationActive={false}
                name="Global importance"
                radius={[0, 4, 4, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="performance-explanation">
          <p>Feature importance shows which engineered inputs the Random Forest relies on most overall. It does not explain the cause of an individual patient&apos;s risk score.</p>
          <p>Values come directly from the fitted 12h RandomForestClassifier feature importances and are mapped through the fitted preprocessing pipeline.</p>
        </div>
      </section>

      <footer className="information-footer">
        <strong>Development 5-fold cross-validation · Development cohort: 2,560 patients</strong>
        <span>Primary checkpoint: 12h · No independent test-set claim</span>
      </footer>
    </div>
  )
}
