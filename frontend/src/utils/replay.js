export const REPLAY_END_MINUTES = 1440
export const REPLAY_STEPS = [15, 60, 180]
const CHECKPOINTS = [360, 720, 1440]

function validMinute(minutes) {
  if (!Number.isInteger(minutes) || minutes < 0 || minutes > REPLAY_END_MINUTES) {
    throw new RangeError('Recorded time must be a whole minute between 0 and 1440')
  }
}

export function formatReplayTime(minutes) {
  validMinute(minutes)
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`
}

export function nextReplayMinute(minutes, step, checkpoints = CHECKPOINTS) {
  validMinute(minutes)
  if (!REPLAY_STEPS.includes(step)) throw new RangeError('Unsupported replay speed')
  // Never skip an assessment, including when resuming from a manual time.
  return Math.min(minutes + step, checkpoints.find((time) => time > minutes) ?? REPLAY_END_MINUTES)
}

export class RecordedReplay {
  constructor({ load, checkpoints = CHECKPOINTS, initialStep = 60, schedule = (callback, delay) => globalThis.setTimeout(callback, delay),
    cancel = (timer) => globalThis.clearTimeout(timer) }) {
    if (!Array.isArray(checkpoints) || !checkpoints.length || checkpoints.at(-1) !== 1440
      || checkpoints.some((time, index) => !Number.isInteger(time) || time <= (checkpoints[index - 1] ?? 0))) {
      throw new RangeError("Replay checkpoints must be ordered and end at 1440")
    }
    this.checkpoints = [...checkpoints]
    if (!REPLAY_STEPS.includes(initialStep)) throw new RangeError('Unsupported replay speed')
    this.load = load
    this.schedule = schedule
    this.cancel = cancel
    this.listeners = new Set()
    this.generation = 0
    this.timer = null
    this.controller = null
    this.state = { minutes: 1440, patient: null, loading: true, playing: false,
      completed: false, error: null, requestedMinutes: null, retryMinutes: 1440, step: initialStep }
    this.getSnapshot = () => this.state
    this.subscribe = (listener) => { this.listeners.add(listener); return () => this.listeners.delete(listener) }
  }

  publish(changes) {
    this.state = { ...this.state, ...changes }
    this.listeners.forEach((listener) => listener())
  }

  cancelWork() {
    if (this.timer !== null) this.cancel(this.timer)
    this.timer = null
    this.controller?.abort()
    this.controller = null
    this.generation += 1
  }

  async request(minutes, { clear = false, autoplay = false } = {}) {
    validMinute(minutes)
    this.cancelWork()
    const generation = this.generation
    const controller = new AbortController()
    this.controller = controller
    this.publish({ loading: true, playing: autoplay, completed: false, error: null,
      requestedMinutes: minutes, retryMinutes: minutes,
      ...(clear ? { patient: null, minutes } : {}) })
    try {
      const patient = await this.load(minutes, controller.signal)
      if (controller.signal.aborted || generation !== this.generation) return
      if (patient?.available_through_minutes !== minutes) throw new Error('The recorded view returned a different time')
      const completed = this.state.playing && minutes === REPLAY_END_MINUTES
      this.controller = null
      this.publish({ patient, minutes, loading: false, requestedMinutes: null, completed,
        playing: this.state.playing && minutes < REPLAY_END_MINUTES })
      this.queueNext()
    } catch (error) {
      if (controller.signal.aborted || generation !== this.generation) return
      this.controller = null
      this.publish({ loading: false, playing: false, requestedMinutes: null, error })
    }
  }

  queueNext() {
    if (!this.state.playing || this.state.loading || this.timer !== null) return
    this.timer = this.schedule(() => {
      this.timer = null
      if (this.state.playing) this.request(nextReplayMinute(this.state.minutes, this.state.step, this.checkpoints), { autoplay: true })
    }, 1000)
  }

  play() {
    if (this.state.loading || this.state.error || !this.state.patient || this.state.playing) return
    if (this.state.minutes === REPLAY_END_MINUTES) return this.request(0, { clear: true, autoplay: true })
    this.publish({ playing: true, completed: false })
    this.queueNext()
  }

  pause({ abortLoading = false } = {}) {
    // A pending admission/manual view can finish while paused, without advancing.
    if (this.state.loading && !this.state.patient && !abortLoading) {
      if (this.timer !== null) this.cancel(this.timer)
      this.timer = null
      this.publish({ playing: false })
      return
    }
    this.cancelWork()
    this.publish({ playing: false, loading: false, requestedMinutes: null })
  }

  seek(minutes) { return this.request(minutes, { clear: true }) }
  reset() { return this.seek(0) }
  retry() { return this.seek(this.state.retryMinutes) }
  setStep(step) {
    if (!REPLAY_STEPS.includes(step)) throw new RangeError('Unsupported replay speed')
    this.publish({ step })
  }
}
