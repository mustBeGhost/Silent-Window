import { formatReplayTime } from '../utils/replay'


export default function RecordedReplayControls({ state, session, checkpoints = ["6h", "12h", "24h"] }) {
  const presetTimes = [...new Set([0, 480, ...checkpoints.map((cp) => parseInt(cp, 10) * 60)])].sort((a, b) => a - b)
  return (
    <section className="panel recorded-replay" aria-labelledby="recorded-replay-title">
      <div className="panel-heading">
        <div>
          <span className="section-kicker">Historical data demo</span>
          <h2 id="recorded-replay-title">Replay recorded observations</h2>
          <p>Watch the first 24 recorded hours unfold. This is not a live hospital feed.</p>
        </div>
        <div className="replay-clock" aria-label="Recorded time since ICU admission">
          <strong>{formatReplayTime(state.minutes)}</strong><span>Hours : minutes since admission</span>
        </div>
      </div>
      <div className="replay-controls">
        <button type="button" onClick={() => session.play()} disabled={state.playing || state.loading || !!state.error || !state.patient}>
          {state.minutes === 1440 ? 'Replay from start' : 'Play replay'}
        </button>
        <button type="button" onClick={() => session.pause()} disabled={!state.playing}>Pause replay</button>
        <button type="button" onClick={() => session.reset()}>Reset to admission</button>
        <label>Replay speed
          <select value={state.step} onChange={(event) => session.setStep(Number(event.target.value))}>
            <option value={15}>15 minutes per step</option>
            <option value={60}>1 hour per step</option>
            <option value={180}>3 hours per step</option>
          </select>
        </label>
        <label>View recorded data through
          <select value={presetTimes.includes(state.minutes) ? state.minutes : ''} onChange={(event) => session.seek(Number(event.target.value))}>
            {!presetTimes.includes(state.minutes) && <option value="" disabled>Replay time {formatReplayTime(state.minutes)}</option>}
            {presetTimes.map((time) => <option value={time} key={time}>{time === 0 ? "Admission (0 hours)" : `${time / 60} hours`}</option>)}
          </select>
        </label>
      </div>
      <p className="replay-status" role="status">{state.error ? 'Replay paused: data could not be loaded.'
        : state.completed ? 'Replay complete: the 24-hour view is available.'
          : state.playing ? 'Playing recorded data. Each step waits for its data.'
            : state.loading ? `Loading recorded data through ${formatReplayTime(state.requestedMinutes ?? state.minutes)}…`
              : 'Paused. Choose a recorded time or play the replay.'}</p>
      <p className="panel-footnote">Each step waits for its data, then waits one second. Scores appear at {checkpoints.join(", ")} only; the primary assessment remains 12h. Jumping to a time pauses playback. Replay pauses when you leave this tab.</p>
    </section>
  )
}
