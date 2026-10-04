export function formatScore(value) {
  return Number.isFinite(value) ? value.toFixed(4) : 'Not assessed'
}

export function assessmentLabel(status) {
  if (status === 'NOT_YET_AVAILABLE') return 'Not available yet'
  if (status === 'INSUFFICIENT_DATA') return 'Insufficient data'
  return 'Assessed'
}
