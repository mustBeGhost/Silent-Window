// Keep polling and duplicate suppression independent of page navigation.
export class RequestNotifications {
  constructor({ load, seenId = 0, onSeen = () => {}, setInterval: schedule = (callback, milliseconds) => setInterval(callback, milliseconds),
    clearInterval: cancel = (timer) => clearInterval(timer), isVisible = () => true }) {
    this.load = load; this.seenId = seenId; this.onSeen = onSeen
    this.schedule = schedule; this.cancel = cancel; this.isVisible = isVisible
    this.state = { pendingCount: null, notice: null, error: null }
    this.listeners = new Set(); this.running = false; this.generation = 0
  }
  getSnapshot = () => this.state
  subscribe = (listener) => { this.listeners.add(listener); return () => this.listeners.delete(listener) }
  publish(state) { this.state = state; this.listeners.forEach((listener) => listener()) }
  start() {
    if (this.running) return
    this.running = true
    this.refresh()
    this.timer = this.schedule(() => { if (this.isVisible()) this.refresh() }, 30000)
  }
  async refresh() {
    if (!this.running) return
    this.controller?.abort()
    const controller = new AbortController()
    this.controller = controller
    const generation = ++this.generation
    try {
      const data = await this.load(controller.signal)
      if (!this.running || generation !== this.generation) return
      let notice = data.pending_count ? this.state.notice : null
      if (data.pending_count && data.latest_pending_id > this.seenId) {
        notice = { latestId: data.latest_pending_id }
        this.seenId = data.latest_pending_id
        try { this.onSeen(this.seenId) } catch { /* Storage may be disabled; memory still suppresses repeats. */ }
      }
      this.publish({ pendingCount: data.pending_count, notice, error: null })
    } catch (error) {
      if (this.running && generation === this.generation && error.name !== 'AbortError') {
        this.publish({ ...this.state, pendingCount: null, error: 'Request count is temporarily unavailable.' })
      }
    }
  }
  dismiss() { this.publish({ ...this.state, notice: null }) }
  stop() { this.running = false; ++this.generation; this.controller?.abort(); this.cancel(this.timer) }
}
