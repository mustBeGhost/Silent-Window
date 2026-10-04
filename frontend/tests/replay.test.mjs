import assert from 'node:assert/strict'
import { test } from 'node:test'
import { RecordedReplay, nextReplayMinute, formatReplayTime } from '../src/utils/replay.js'

function harness() {
  const timers = new Map()
  const requests = []
  let id = 0
  const session = new RecordedReplay({
    load: (minutes, signal) => new Promise((resolve, reject) => requests.push({ minutes, signal, resolve, reject })),
    schedule: (callback) => { timers.set(++id, callback); return id },
    cancel: (timer) => timers.delete(timer),
  })
  const tick = () => {
    const [timer, callback] = timers.entries().next().value
    timers.delete(timer)
    callback()
  }
  const resolve = async (index) => {
    requests[index].resolve({ available_through_minutes: requests[index].minutes })
    await new Promise(setImmediate)
  }
  return { session, requests, timers, tick, resolve }
}

test('all replay speeds include every checkpoint and stop at 24h', () => {
  for (const step of [15, 60, 180]) {
    const times = [0]
    while (times.at(-1) < 1440) times.push(nextReplayMinute(times.at(-1), step))
    for (const checkpoint of [360, 720, 1440]) assert.ok(times.includes(checkpoint))
    assert.equal(nextReplayMinute(1440, step), 1440)
  }
  assert.equal(nextReplayMinute(350, 180), 360)
  assert.equal(nextReplayMinute(710, 180), 720)
  assert.equal(formatReplayTime(375), '06:15')
  assert.throws(() => nextReplayMinute(0, 999), RangeError)
  assert.throws(() => formatReplayTime(-1), RangeError)
})

test('start removes the full future view and advances only after a response', async () => {
  const h = harness()
  h.session.seek(1440)
  await h.resolve(0)
  h.session.play()
  assert.equal(h.session.state.patient, null)
  assert.equal(h.session.state.minutes, 0)
  assert.equal(h.requests[1].minutes, 0)
  assert.equal(h.timers.size, 0)
  await h.resolve(1)
  assert.equal(h.timers.size, 1)
  h.tick()
  assert.equal(h.requests[2].minutes, 60)
  assert.equal(h.session.state.minutes, 0)
  assert.equal(h.session.state.patient.available_through_minutes, 0)
  assert.equal(h.timers.size, 0)
  h.session.play() // repeated play cannot create another request/timer
  assert.equal(h.requests.length, 3)
  await h.resolve(2)
  assert.equal(h.session.state.minutes, 60)
  h.session.pause({ abortLoading: true })
})

test('pause cancels an advancing request and ignores its late response', async () => {
  const h = harness()
  h.session.seek(0)
  await h.resolve(0)
  h.session.play()
  h.tick()
  h.session.pause()
  assert.equal(h.requests[1].signal.aborted, true)
  await h.resolve(1) // simulate a transport that ignores cancellation
  assert.equal(h.session.state.minutes, 0)
  assert.equal(h.session.state.playing, false)
  assert.equal(h.timers.size, 0)
  h.session.play()
  h.tick()
  assert.equal(h.requests[2].minutes, 60)
  h.session.pause({ abortLoading: true })
})

test('reset hides a future view immediately and cannot be replaced by an old response', async () => {
  const h = harness()
  h.session.seek(1440)
  h.session.reset()
  assert.equal(h.session.state.minutes, 0)
  assert.equal(h.session.state.patient, null)
  assert.equal(h.requests[0].signal.aborted, true)
  await h.resolve(1)
  await h.resolve(0)
  assert.equal(h.session.state.patient.available_through_minutes, 0)
  assert.equal(h.session.state.playing, false)
  assert.equal(h.timers.size, 0)
})

test('pausing while admission loads allows that view to finish without starting playback', async () => {
  const h = harness()
  h.session.seek(1440)
  await h.resolve(0)
  h.session.play()
  h.session.pause()
  await h.resolve(1)
  assert.equal(h.session.state.minutes, 0)
  assert.equal(h.session.state.loading, false)
  assert.equal(h.session.state.playing, false)
  assert.equal(h.timers.size, 0)
})

test('failed data stops playback at the last view and retry stays paused', async () => {
  const h = harness()
  h.session.seek(0)
  await h.resolve(0)
  h.session.play()
  h.tick()
  h.requests[1].reject(new Error('Offline'))
  await new Promise(setImmediate)
  assert.equal(h.session.state.minutes, 0)
  assert.equal(h.session.state.playing, false)
  assert.equal(h.session.state.error.message, 'Offline')
  assert.equal(h.timers.size, 0)
  h.session.retry()
  assert.equal(h.requests[2].minutes, 60)
  await h.resolve(2)
  assert.equal(h.session.state.minutes, 60)
  assert.equal(h.session.state.error, null)
  assert.equal(h.session.state.playing, false)
})

test('speed changes apply to the next step, manual seeking pauses, and end stops timers', async () => {
  const h = harness()
  h.session.seek(350)
  await h.resolve(0)
  h.session.setStep(180)
  h.session.play()
  h.tick()
  assert.equal(h.requests[1].minutes, 360)
  h.session.seek(1260)
  assert.equal(h.requests[1].signal.aborted, true)
  await h.resolve(2)
  assert.equal(h.session.state.playing, false)
  assert.equal(h.timers.size, 0)
  h.session.play()
  h.tick()
  await h.resolve(3)
  assert.equal(h.session.state.minutes, 1440)
  assert.equal(h.session.state.completed, true)
  assert.equal(h.session.state.playing, false)
  assert.equal(h.timers.size, 0)
})

test('unmount cleanup cancels every request and supports a clean strict-mode restart', async () => {
  const h = harness()
  h.session.seek(1440)
  h.session.pause({ abortLoading: true })
  assert.equal(h.requests[0].signal.aborted, true)
  h.session.seek(1440)
  await h.resolve(1)
  await h.resolve(0)
  assert.equal(h.session.state.loading, false)
  assert.equal(h.session.state.patient.available_through_minutes, 1440)
  h.session.play()
  h.session.pause({ abortLoading: true })
  await h.resolve(2)
  assert.equal(h.session.state.patient, null)
  assert.equal(h.timers.size, 0)
})

test('a response for a different cutoff is never displayed', async () => {
  const h = harness()
  h.session.seek(360)
  h.requests[0].resolve({ available_through_minutes: 1440 })
  await new Promise(setImmediate)
  assert.equal(h.session.state.patient, null)
  assert.equal(h.session.state.playing, false)
  assert.match(h.session.state.error.message, /different time/)
})

test('default timers preserve the browser global receiver', async () => {
  const originalSchedule = globalThis.setTimeout
  const originalCancel = globalThis.clearTimeout
  let scheduled = 0
  let canceled = 0
  try {
    globalThis.setTimeout = function () { assert.equal(this, globalThis); scheduled += 1; return 77 }
    globalThis.clearTimeout = function (handle) { assert.equal(this, globalThis); assert.equal(handle, 77); canceled += 1 }
    const session = new RecordedReplay({ load: async (minutes) => ({ available_through_minutes: minutes }) })
    await session.seek(0)
    session.play()
    session.pause()
    assert.equal(scheduled, 1)
    assert.equal(canceled, 1)
  } finally {
    globalThis.setTimeout = originalSchedule
    globalThis.clearTimeout = originalCancel
  }
})
