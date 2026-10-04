import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis } from 'recharts'

const VITAL_DISPLAY = {
  HR: { title: 'Heart rate', unit: 'bpm', color: '#ffaaa3' },
  MAP: { title: 'Mean arterial pressure', unit: 'mmHg', color: '#ffbf69' },
  GCS: { title: 'GCS', unit: '/ 15', color: '#7bd0ff' },
  Creatinine: { title: 'Creatinine', unit: 'mg/dL', color: '#c5a3ff' },
}

function formatValue(value) {
  return Number.isInteger(value) ? value : Number(value.toFixed(2))
}

export default function VitalChart({ parameter, measurements, availableThroughMinutes = 1440 }) {
  const display = VITAL_DISPLAY[parameter]
  const latest = measurements.at(-1)

  return (
    <article className="vital-card">
      <div className="vital-card-top">
        <span>{display.title}</span>
        <strong style={{ color: display.color }}>{measurements.length} observations</strong>
      </div>
      <div className="vital-value" style={{ color: display.color }}>
        {latest ? formatValue(latest.value) : '--'} <span>{latest ? display.unit : `No data through ${availableThroughMinutes / 60}h`}</span>
      </div>
      {measurements.length > 0 ? (
        <div className="vital-chart">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={measurements} margin={{ top: 5, right: 3, bottom: 0, left: 3 }}>
              <XAxis
                dataKey="time_minutes"
                domain={[0, 1440]}
                tickFormatter={(value) => `${Math.round(value / 60)}h`}
                ticks={[0, 360, 720, 1440]}
                type="number"
                tick={{ fill: '#596678', fontSize: 9 }}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip
                contentStyle={{ background: '#111827', border: '1px solid #2d394f', borderRadius: 6, fontSize: 11 }}
                formatter={(value) => [`${formatValue(value)} ${display.unit}`, display.title]}
                labelFormatter={(value) => `Minute ${value}`}
                labelStyle={{ color: '#9ca3af' }}
              />
              <Line dataKey="value" type="linear" stroke={display.color} strokeWidth={0} dot={{ r: 2 }} activeDot={{ r: 4 }} connectNulls={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="vital-empty">No observations supplied for this measurement.</div>
      )}
    </article>
  )
}
