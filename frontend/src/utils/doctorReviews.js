export function validateReviewSummary(data) {
  if (!Number.isInteger(data?.open_count) || data.open_count < 0 || !Array.isArray(data.pending_ids)
    || !data.pending_ids.every((id) => Number.isInteger(id) && id > 0)
    || !Array.isArray(data.pending_keys) || data.pending_keys.length !== data.pending_ids.length
    || !data.pending_keys.every((key, index) => typeof key === 'string' && /^(?:[1-9]\d*):(?:0|[1-9]\d*)$/.test(key) && key.split(':')[0] === String(data.pending_ids[index]))) throw new Error('Review notification counts could not be loaded.')
  return data
}
export function unseenReviewKeys(keys, seen) { return keys.filter((key) => !seen.has(key)) }
