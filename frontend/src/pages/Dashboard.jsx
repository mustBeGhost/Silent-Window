import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { modelCheckpoints } from '../services/api'
import { useAuth } from '../context/Auth'
import { permissions } from '../permissions'
import { useModelProfile } from '../context/ModelProfile'

import PatientTable from '../components/PatientTable'
import StatCard from '../components/StatCard'
import {
  getGlobalIndexStatus,
  getPatients,
  getSystemStatus,
  prepareGlobalIndex,
} from '../services/api'

const PAGE_SIZE = 25
const GLOBAL_POLL_INTERVAL_MS = 1500
const EMPTY_PAGE = {
  items: [],
  page: 1,
  page_size: PAGE_SIZE,
  total: 0,
  total_pages: 0,
  cohort_total: 3200,
  cached_assessments: 0,
  result_scope: 'cohort',
  assessment_counts: null,
}

function StatusItem({ label, value, tone }) {
  return (
    <div className="system-status-item">
      <span>{label}</span>
      <strong className={`system-status-value status-${tone}`}>
        <i aria-hidden="true" />
        {value}
      </strong>
    </div>
  )
}

export default function Dashboard() {
  const { modelProfile } = useModelProfile()
  const { user } = useAuth()
  const pageSize = user?.preferences?.page_size || 25
  const unitAccess = !user || permissions(user.role).unit
  const [patientPage, setPatientPage] = useState(() => ({ ...EMPTY_PAGE, cohort_total: unitAccess ? 3200 : 0 }))
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)
  const [page, setPage] = useState(1)
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [risk, setRisk] = useState('')
  const [alert, setAlert] = useState('')
  const [sortOrder, setSortOrder] = useState('asc')
  const [scope, setScope] = useState('page')
  const [requestKey, setRequestKey] = useState(0)
  const [systemStatus, setSystemStatus] = useState(null)
  const [systemState, setSystemState] = useState('loading')
  const [globalState, setGlobalState] = useState('idle')
  const [globalStatus, setGlobalStatus] = useState(null)
  const [globalError, setGlobalError] = useState(null)
  const [globalFlowKey, setGlobalFlowKey] = useState(0)
  const retryFailedBuild = useRef(false)

  const loadPatients = useCallback(() => {
    setRequestKey((value) => value + 1)
  }, [])

  useEffect(() => {
    if (scope !== 'page') return undefined

    const controller = new AbortController()
    setStatus('loading')
    setError(null)
    getPatients({
      modelProfile,
      page,
      pageSize,
      search,
      scope: 'page',
      sortOrder,
      signal: controller.signal,
    })
      .then((data) => {
        setPatientPage(data)
        setStatus('ready')
      })
      .catch((requestError) => {
        if (requestError.name !== 'AbortError') {
          setError(requestError)
          setStatus('error')
        }
      })
    return () => controller.abort()
  }, [modelProfile, pageSize, page, requestKey, scope, search, sortOrder])

  useEffect(() => {
    if (scope !== 'all') return undefined

    const controller = new AbortController()
    let pollTimer = null
    let cancelled = false
    const retryFailed = retryFailedBuild.current
    retryFailedBuild.current = false

    async function checkIndex({ mayPrepare = false } = {}) {
      try {
        let indexStatus = await getGlobalIndexStatus({
          modelProfile,
          signal: controller.signal,
        })
        if (cancelled) return
        setGlobalStatus(indexStatus)
        setGlobalError(null)

        const shouldPrepare = mayPrepare && (
          indexStatus.state === 'not_started'
          || (indexStatus.state === 'failed' && retryFailed)
        )
        if (shouldPrepare) {
          indexStatus = await prepareGlobalIndex({
            modelProfile,
            signal: controller.signal,
          })
          if (cancelled) return
          setGlobalStatus(indexStatus)
        }

        if (indexStatus.state === 'ready') {
          setGlobalState('ready')
          return
        }
        if (indexStatus.state === 'failed') {
          setGlobalState('failed')
          return
        }

        setGlobalState('building')
        pollTimer = window.setTimeout(
          () => checkIndex(),
          GLOBAL_POLL_INTERVAL_MS,
        )
      } catch (requestError) {
        if (!cancelled && requestError.name !== 'AbortError') {
          setGlobalError(requestError)
          setGlobalState('error')
        }
      }
    }

    setGlobalState('checking')
    setGlobalError(null)
    checkIndex({ mayPrepare: true })

    return () => {
      cancelled = true
      controller.abort()
      if (pollTimer !== null) window.clearTimeout(pollTimer)
    }
  }, [modelProfile, globalFlowKey, scope])

  useEffect(() => {
    if (scope !== 'all' || globalState !== 'ready') return undefined

    const controller = new AbortController()
    setStatus('loading')
    setError(null)
    getPatients({
      modelProfile,
      page,
      pageSize,
      search,
      risk,
      alert,
      scope: 'all',
      sortOrder,
      signal: controller.signal,
    })
      .then((data) => {
        setPatientPage(data)
        setStatus('ready')
      })
      .catch((requestError) => {
        if (requestError.name === 'AbortError') return
        if (requestError.status === 409) {
          setGlobalState('checking')
          setGlobalFlowKey((value) => value + 1)
          return
        }
        setError(requestError)
        setStatus('error')
      })
    return () => controller.abort()
  }, [modelProfile, pageSize, alert, globalState, page, requestKey, risk, scope, search, sortOrder])

  useEffect(() => {
    const controller = new AbortController()
    setSystemState('loading')
    getSystemStatus({ signal: controller.signal, modelProfile })
      .then((data) => {
        setSystemStatus(data)
        setSystemState('ready')
      })
      .catch((requestError) => {
        if (requestError.name !== 'AbortError') {
          setSystemStatus(null)
          setSystemState('error')
        }
      })
    return () => controller.abort()
  }, [modelProfile])

  const loadedPatients = patientPage.items
  const patients = useMemo(() => (
    scope === 'page'
      ? loadedPatients.filter((patient) => (
        (!risk || patient.risk_level === risk)
        && (!alert || patient.alert_state === alert)
      ))
      : loadedPatients
  ), [alert, loadedPatients, risk, scope])
  const pageCounts = useMemo(() => ({
    high_risk: loadedPatients.filter((patient) => patient.risk_level === 'HIGH').length,
    watch: loadedPatients.filter((patient) => patient.alert_state === 'WATCH').length,
    no_alert: loadedPatients.filter((patient) => patient.alert_state === 'NO_ALERT').length,
    not_assessed: loadedPatients.filter((patient) => patient.assessment_status !== 'READY').length,
  }), [loadedPatients])
  const completeCounts = patientPage.assessment_counts
  const displayedCounts = scope === 'all'
    ? (completeCounts || { high_risk: '--', watch: '--', no_alert: '--', not_assessed: '--' })
    : pageCounts
  const countEyebrow = scope === 'all' ? (unitAccess ? 'All patient records' : 'All assigned records') : 'Loaded page'
  const countNote = scope === 'all'
    ? completeCounts
      ? `Across ${patientPage.cohort_total.toLocaleString()} patient records`
      : 'Complete counts load when assessments are ready'
    : `Among ${loadedPatients.length} patient records`

  const displayTotalPages = Math.max(patientPage.total_pages, 1)
  const rangeStart = patientPage.total === 0
    ? 0
    : ((patientPage.page - 1) * patientPage.page_size) + 1
  const rangeEnd = Math.min(
    patientPage.page * patientPage.page_size,
    patientPage.total,
  )
  const localFilterActive = scope === 'page' && Boolean(risk || alert)
  const globalPreparing = scope === 'all' && ['checking', 'building'].includes(globalState)
  const globalUnavailable = scope === 'all' && ['failed', 'error'].includes(globalState)
  const controlsDisabled = scope === 'all' && globalState !== 'ready'
  const completedPatients = globalStatus?.completed_patients || 0
  const totalPatients = globalStatus?.total_patients || patientPage.cohort_total
  const progress = totalPatients > 0
    ? Math.min(100, Math.round((completedPatients / totalPatients) * 100))
    : 0

  function applySearch(event) {
    event.preventDefault()
    setPage(1)
    setSearch(searchInput.trim())
  }

  function changeSort(event) {
    setPage(1)
    setSortOrder(event.target.value)
  }

  function changeAssessmentFilter(setter) {
    return (event) => {
      if (scope === 'all') setPage(1)
      setter(event.target.value)
    }
  }

  function changeScope(nextScope) {
    if (nextScope === scope) return
    setScope(nextScope)
    setPage(1)
    setPatientPage({ ...EMPTY_PAGE, cohort_total: patientPage.cohort_total, result_scope: nextScope === 'all' ? 'complete_assessment_index' : 'cohort' })
    setStatus(nextScope === 'page' ? 'loading' : 'idle')
    setError(null)
    if (nextScope === 'all') {
      setGlobalState('checking')
      setGlobalError(null)
    }
  }

  function retryGlobalPreparation() {
    retryFailedBuild.current = globalState === 'failed'
    setGlobalState('checking')
    setGlobalError(null)
    setGlobalFlowKey((value) => value + 1)
  }

  return (
    <div className="page dashboard-page">
      <section className="page-heading dashboard-heading">
        <div>
          <span className="section-kicker">{unitAccess ? "Full cohort patient assessments" : "Your assigned patients"}</span>
          <h1>{unitAccess ? "ICU Patient Overview" : "My Assigned Patients"}</h1>
          <p>Hospital-death risk scores from recorded ICU data at {modelCheckpoints(modelProfile).join(", ")}. Scores are not verified probabilities or live assessments.</p>
        </div>
        <div className="dashboard-controls">
          <form className="search-box" onSubmit={applySearch}>
            <span aria-hidden="true">⌕</span>
            <label className="sr-only" htmlFor="patient-search">Search patients</label>
            <input
              id="patient-search"
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="Search patient ID"
              value={searchInput}
            />
            <button type="submit">Search</button>
          </form>
          <fieldset className="filter-scope-control">
            <legend>Filter scope</legend>
            <label className={`filter-scope-option ${scope === 'page' ? 'active' : ''}`}>
              <input
                checked={scope === 'page'}
                name="filter-scope"
                onChange={() => changeScope('page')}
                type="radio"
              />
              <span>Current Page</span>
            </label>
            <label className={`filter-scope-option ${scope === 'all' ? 'active' : ''}`}>
              <input
                checked={scope === 'all'}
                name="filter-scope"
                onChange={() => changeScope('all')}
                type="radio"
              />
              <span>{unitAccess ? 'All Patients' : 'All Assigned Patients'}</span>
            </label>
          </fieldset>
          <div className="queue-filter-grid">
            <label>
              <span className="sr-only">Risk filter</span>
              <select
                disabled={controlsDisabled}
                onChange={changeAssessmentFilter(setRisk)}
                value={risk}
              >
                <option value="">All risks</option>
                <option value="LOW">Low</option>
                <option value="MEDIUM">Medium</option>
                <option value="HIGH">High</option>
              </select>
            </label>
            <label>
              <span className="sr-only">Alert filter</span>
              <select
                disabled={controlsDisabled}
                onChange={changeAssessmentFilter(setAlert)}
                value={alert}
              >
                <option value="">All alerts</option>
                <option value="NO_ALERT">No alert</option>
                <option value="WATCH">Watch</option>
                <option value="HIGH_ALERT">High alert</option>
              </select>
            </label>
            <label>
              <span className="sr-only">Patient ID sorting</span>
              <select disabled={controlsDisabled} onChange={changeSort} value={sortOrder}>
                <option value="asc">Patient ID ascending</option>
                <option value="desc">Patient ID descending</option>
              </select>
            </label>
          </div>
        </div>
      </section>

      <section className="system-status-panel" aria-labelledby="system-status-title">
        <div className="system-status-heading">
          <div>
            <span className="section-kicker">System status</span>
            <h2 id="system-status-title">Runtime readiness</h2>
          </div>
          <p>
            {systemState === 'loading' && 'Checking backend readiness...'}
            {systemState === 'error' && 'System status could not be verified.'}
            {systemState === 'ready' && (systemStatus.status === 'ok'
              ? 'Backend components report ready.'
              : 'One or more backend components are unavailable.')}
          </p>
        </div>

        <div className="system-status-grid">
          <div className="system-status-checks">
            <StatusItem
              label="API"
              tone={systemState === 'ready' ? 'ready' : systemState === 'error' ? 'unavailable' : 'pending'}
              value={systemState === 'ready' ? 'Online' : systemState === 'error' ? 'Unavailable' : 'Checking'}
            />
            <StatusItem
              label="ML models"
              tone={systemState === 'ready' && systemStatus.models === 'ready' ? 'ready' : systemState === 'ready' ? 'unavailable' : 'pending'}
              value={systemState === 'ready' ? (systemStatus.models === 'ready' ? 'Ready' : 'Unavailable') : 'Not verified'}
            />
            <StatusItem
              label="Patient data"
              tone={systemState === 'ready' && systemStatus.patient_data === 'available' ? 'ready' : systemState === 'ready' ? 'unavailable' : 'pending'}
              value={systemState === 'ready' ? (systemStatus.patient_data === 'available' ? 'Available' : 'Unavailable') : 'Not verified'}
            />
          </div>

          <dl className="system-metadata">
            <div><dt>Model family</dt><dd>{systemStatus?.model_family || '--'}</dd></div>
            <div><dt>Primary assessment</dt><dd>{systemStatus?.primary_checkpoint || '--'}</dd></div>
            <div><dt>Supported</dt><dd>{systemStatus ? systemStatus.supported_checkpoints.join(' / ') : '--'}</dd></div>
          </dl>
        </div>
      </section>

      <section className="stat-grid" aria-label="Patient monitoring summary">
        <StatCard eyebrow="Available cohort" label="Cohort Size" value={patientPage.cohort_total} tone="info" note={unitAccess ? "All available patients" : "Patients assigned to you"} icon="▤" />
        <StatCard eyebrow={countEyebrow} label="High Risk" value={displayedCounts.high_risk} tone="high" note={countNote} icon="△" />
        <StatCard eyebrow={countEyebrow} label="Watch" value={displayedCounts.watch} tone="watch" note={countNote} icon="◉" />
        <StatCard eyebrow={countEyebrow} label="No Alert" value={displayedCounts.no_alert} tone="low" note={countNote} icon="✓" />
      </section>

      <section className="queue-panel">
        <p className="panel-footnote">Not assessed: {displayedCounts.not_assessed} patient records. These records are excluded from risk and alert counts. “No Alert” does not mean the patient is safe.</p>
        <div className="queue-heading">
          <div>
            <div className="title-with-chip">
              <h2>Patient Risk Queue</h2>
              <span className="info-chip">
                {scope === 'all'
                  ? unitAccess ? 'Scope: complete patient cohort' : 'Scope: all assigned patients'
                  : `Loaded page: ${loadedPatients.length} patient records`}
              </span>
              {scope === 'page' && (
                <span className="info-chip">
                  Showing: {patients.length} of {loadedPatients.length} on this page
                </span>
              )}
              {scope === 'all' && status === 'ready' && (
                <span className="info-chip">
                  Showing {rangeStart}-{rangeEnd} of {patientPage.total} matching patients
                </span>
              )}
            </div>
            <p>
              {patientPage.cohort_total.toLocaleString()} {unitAccess ? "patients in the available cohort." : "patients assigned to you."}
              {scope === 'page' && patientPage.total > 0 && ` Loaded cohort positions ${rangeStart}-${rangeEnd} of ${patientPage.total}.`}
              {scope === 'all' && status === 'ready' && ' Filters apply to the complete assessment index before pagination.'}
            </p>
          </div>
          <div className="risk-legend"><span className="high">● High</span><span className="watch">● Watch</span><span className="low">● Low</span></div>
        </div>

        {globalPreparing && (
          <div className="state-panel global-index-state" role="status">
            <span className="loader" />
            <strong>
              {globalState === 'checking'
                ? 'Checking complete assessment readiness...'
                : `Preparing assessments for all ${totalPatients.toLocaleString()} patients`}
            </strong>
            {globalState === 'building' && (
              <>
                <span>{completedPatients.toLocaleString()} / {totalPatients.toLocaleString()} assessed</span>
                <div
                  aria-label={`${progress}% complete`}
                  aria-valuemax="100"
                  aria-valuemin="0"
                  aria-valuenow={progress}
                  className="global-progress"
                  role="progressbar"
                >
                  <span style={{ width: `${progress}%` }} />
                </div>
                <small>The first complete preparation may take about 1-2 minutes. Current Page remains available.</small>
              </>
            )}
          </div>
        )}
        {globalUnavailable && (
          <div className="state-panel error-state" role="alert">
            <strong>
              {globalState === 'failed'
                ? 'Complete patient assessments could not be prepared.'
                : 'Complete assessment status could not be checked.'}
            </strong>
            <span>
              {globalError?.status
                ? 'The assessment service is temporarily unavailable.'
                : 'Check that the backend is running, then retry.'}
            </span>
            <button onClick={retryGlobalPreparation} type="button">
              {globalState === 'failed' ? 'Retry preparation' : 'Retry status check'}
            </button>
          </div>
        )}
        {!globalPreparing && !globalUnavailable && status === 'loading' && (
          <div className="state-panel" role="status"><span className="loader" /> Loading patient risk queue...</div>
        )}
        {!globalPreparing && !globalUnavailable && status === 'error' && (
          <div className="state-panel error-state" role="alert">
            <strong>Patient data could not be loaded.</strong>
            <span>
              {error?.status
                ? 'Patient assessments are temporarily unavailable.'
                : 'The backend may be unavailable.'}
            </span>
            <button onClick={loadPatients} type="button">Retry</button>
          </div>
        )}
        {!globalPreparing && !globalUnavailable && status === 'ready' && loadedPatients.length === 0 && scope === 'all' && (
          <div className="state-panel">
            <strong>No patients across the complete assessed cohort match the selected filters.</strong>
            <span>Try a different patient ID, risk level, or alert state.</span>
          </div>
        )}
        {!globalPreparing && !globalUnavailable && status === 'ready' && loadedPatients.length === 0 && scope === 'page' && (
          <div className="state-panel">
            <strong>{search ? 'No patients match this search.' : 'No patients are available.'}</strong>
            <span>
              {search
                ? 'Try a different public patient ID.'
                : unitAccess ? 'The patient cohort returned no records.' : 'Ask an administrator or ICU coordinator to assign patients to your account.'}
            </span>
          </div>
        )}
        {status === 'ready' && loadedPatients.length > 0 && patients.length === 0 && localFilterActive && (
          <div className="state-panel">
            <strong>No patients on this loaded page match the selected filters.</strong>
            <span>Try another filter or move to the previous or next cohort page.</span>
          </div>
        )}
        {!globalPreparing && !globalUnavailable && status === 'ready' && patients.length > 0 && <PatientTable patients={patients} />}
        {!globalPreparing && !globalUnavailable && status === 'ready' && (
          <nav className="pagination-bar" aria-label="Patient queue pages">
            <button
              disabled={patientPage.page <= 1}
              onClick={() => setPage((value) => Math.max(1, value - 1))}
              type="button"
            >
              Previous
            </button>
            <span>Page {patientPage.page} of {displayTotalPages}</span>
            <button
              disabled={patientPage.total_pages === 0 || patientPage.page >= patientPage.total_pages}
              onClick={() => setPage((value) => value + 1)}
              type="button"
            >
              Next
            </button>
          </nav>
        )}
      </section>

      <footer className="information-footer">
        <strong>API inference at supported {modelCheckpoints(modelProfile).join(" / ")} checkpoints.</strong>
        <span>Primary assessment: 12h · Model: {modelProfile === "expanded" ? "Calibrated Random Forest V4" : modelProfile === "calibrated" ? "Calibrated Random Forest V3" : "Random Forest V2"}</span>
      </footer>
    </div>
  )
}
