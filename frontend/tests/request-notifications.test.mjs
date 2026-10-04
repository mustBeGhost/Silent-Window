import assert from 'node:assert/strict'
import { test } from 'node:test'
import { RequestNotifications } from '../src/utils/requestNotifications.js'

const tick = () => new Promise((resolve) => setImmediate(resolve))
function fixture(options = {}) {
  let payload = { pending_count: 1, latest_pending_id: 10 }
  let timer; let loads = 0; const seen = []; const cleared = []
  const poller = new RequestNotifications({ load: async () => { loads++; return payload }, onSeen: (id) => seen.push(id),
    setInterval: (callback, milliseconds) => { assert.equal(milliseconds, 30000); timer = callback; return 42 },
    clearInterval: (id) => cleared.push(id), ...options })
  return { poller, seen, cleared, timer: () => timer(), loads: () => loads, set: (value) => { payload = value } }
}

test('initial requests notify once, dismissal survives refresh, and a new ID not just a bigger count notifies', async () => {
  const f = fixture(); f.poller.start(); await tick()
  assert.equal(f.poller.getSnapshot().pendingCount, 1)
  assert.deepEqual(f.seen, [10]); assert.ok(f.poller.getSnapshot().notice)
  f.poller.dismiss(); await f.poller.refresh()
  assert.equal(f.poller.getSnapshot().notice, null)
  f.set({ pending_count: 1, latest_pending_id: 11 }); await f.poller.refresh()
  assert.deepEqual(f.seen, [10, 11]); assert.equal(f.poller.getSnapshot().notice.latestId, 11)
  f.set({ pending_count: 0, latest_pending_id: 0 }); await f.poller.refresh()
  assert.equal(f.poller.getSnapshot().notice, null); assert.equal(f.poller.getSnapshot().pendingCount, 0)
  f.poller.stop()
})

test('saved seen ID suppresses repeat popup after page reload while count remains available', async () => {
  const f = fixture({ seenId: 10 }); f.poller.start(); await tick()
  assert.equal(f.poller.getSnapshot().notice, null); assert.equal(f.poller.getSnapshot().pendingCount, 1)
  assert.deepEqual(f.seen, []); f.poller.stop()
})

test('older pending IDs after review never trigger the same popup again', async () => {
  const f = fixture(); f.poller.start(); await tick(); f.poller.dismiss()
  f.set({ pending_count: 2, latest_pending_id: 8 }); await f.poller.refresh()
  assert.equal(f.poller.getSnapshot().notice, null); assert.equal(f.poller.getSnapshot().pendingCount, 2)
  f.poller.stop()
})

test('polling skips hidden pages, does not start twice and cleans up its timer', async () => {
  let visible = false
  const f = fixture({ isVisible: () => visible }); f.poller.start(); await tick(); f.poller.start()
  const first = f.loads(); f.timer(); await tick(); assert.equal(f.loads(), first)
  visible = true; f.timer(); await tick(); assert.equal(f.loads(), first + 1)
  f.poller.stop(); assert.deepEqual(f.cleared, [42])
  await f.poller.refresh(); assert.equal(f.loads(), first + 1)
})

test('late responses after logout or a newer refresh cannot restore private notification data', async () => {
  const pending = []
  const f = fixture({ load: (signal) => new Promise((resolve) => pending.push({ signal, resolve })) })
  f.poller.start(); const refresh = f.poller.refresh()
  assert.ok(pending[0].signal.aborted)
  pending[1].resolve({ pending_count: 0, latest_pending_id: 0 }); await refresh
  pending[0].resolve({ pending_count: 8, latest_pending_id: 99 }); await tick()
  assert.equal(f.poller.getSnapshot().pendingCount, 0)
  const next = f.poller.refresh(); f.poller.stop()
  pending[2].resolve({ pending_count: 9, latest_pending_id: 100 }); await next
  assert.equal(f.poller.getSnapshot().pendingCount, 0); assert.deepEqual(f.seen, [])
})

test('failed requests show unavailable instead of a false zero and storage failures do not repeat popups', async () => {
  let fail = true
  const f = fixture({ onSeen: () => { throw new Error('storage disabled') }, load: async () => {
    if (fail) throw new Error('offline')
    return { pending_count: 3, latest_pending_id: 20 }
  } })
  f.poller.start(); await tick()
  assert.equal(f.poller.getSnapshot().pendingCount, null); assert.match(f.poller.getSnapshot().error, /unavailable/)
  fail = false; await f.poller.refresh(); assert.equal(f.poller.getSnapshot().pendingCount, 3)
  f.poller.dismiss(); await f.poller.refresh(); assert.equal(f.poller.getSnapshot().notice, null)
  f.poller.stop()
})
