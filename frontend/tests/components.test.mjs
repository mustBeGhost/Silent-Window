import assert from 'node:assert/strict'
import { test } from 'node:test'
import React from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'
import { readFileSync } from 'node:fs'

test('assessment components render missing and future results safely', async (t) => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false } })
  try {
    const { default: AlertExplanation } = await server.ssrLoadModule('/src/components/AlertExplanation.jsx')
    const { default: RiskTrajectory } = await server.ssrLoadModule('/src/components/RiskTrajectory.jsx')
    const { default: Header } = await server.ssrLoadModule('/src/components/layout/Header.jsx')
    const { default: ModelNotice } = await server.ssrLoadModule('/src/components/ModelNotice.jsx')
    const { ModelProfileContext } = await server.ssrLoadModule('/src/context/ModelProfile.jsx')
    const { default: ModelPerformance } = await server.ssrLoadModule('/src/pages/ModelPerformance.jsx')
    const { default: Sidebar } = await server.ssrLoadModule('/src/components/layout/Sidebar.jsx')
    const { default: RecallExperiments } = await server.ssrLoadModule('/src/components/RecallExperiments.jsx')
    const { default: ModelImprovements } = await server.ssrLoadModule('/src/components/ModelImprovements.jsx')
    const { default: ForestTuning } = await server.ssrLoadModule('/src/components/ForestTuning.jsx')
    const { default: RecordedReplayControls } = await server.ssrLoadModule('/src/components/RecordedReplay.jsx')
    const { default: PatientDetails } = await server.ssrLoadModule('/src/pages/PatientDetails.jsx')
    const point = (checkpoint, status = 'INSUFFICIENT_DATA') => ({
      checkpoint, assessment_status: status, assessment_reason: 'No usable measurements.',
      temporal_observation_count: 0, risk_probability: null, risk_level: null, alert_state: null,
    })

    await t.test('missing assessments do not render a zero score or no-alert badge', () => {
      const checkpoints = ['6h', '12h', '24h'].map((checkpoint) => point(checkpoint))
      const html = renderToStaticMarkup(React.createElement(AlertExplanation, { checkpoints }))
      assert.match(html, /Insufficient data/)
      assert.match(html, /Not assessed/)
      assert.doesNotMatch(html, /alert-no_alert/)
      assert.doesNotMatch(html, /0\.0000/)
    })

    await t.test('future checkpoints render their unavailable labels', () => {
      const points = ['6h', '12h', '24h'].map((checkpoint) => point(checkpoint, 'NOT_YET_AVAILABLE'))
      const html = renderToStaticMarkup(React.createElement(RiskTrajectory, { points }))
      assert.match(html, /Not available yet/)
      assert.doesNotMatch(html, /risk-low/)
    })

    await t.test('an elevated score following a missing assessment explains WATCH', () => {
      const checkpoints = [point('6h'), {
        ...point('12h', 'READY'), assessment_reason: null,
        temporal_observation_count: 1, risk_probability: 0.7, risk_level: 'HIGH', alert_state: 'WATCH',
      }, point('24h', 'NOT_YET_AVAILABLE')]
      const html = renderToStaticMarkup(React.createElement(AlertExplanation, { checkpoints }))
      assert.match(html, /previous checkpoint was not assessed/)
      assert.match(html, /0\.7000/)
    })
    await t.test('candidate selection shows its own thresholds and research limitation', () => {
      const context = { modelProfile: 'calibrated', setModelProfile: () => {}, optionsState: 'ready', options: [
        { id: 'original', available: true, medium_threshold: 0.4, high_threshold: 0.55 },
        { id: 'calibrated', available: true, medium_threshold: 0.12, high_threshold: 0.28 },
      ] }
      const html = renderToStaticMarkup(React.createElement(ModelProfileContext.Provider, { value: context },
        React.createElement(MemoryRouter, null, React.createElement(Header), React.createElement(ModelNotice), React.createElement(ModelPerformance))))
      assert.match(html, /value="calibrated" selected=""/)
      assert.match(html, /medium 0\.12/)
      assert.match(html, /high 0\.28/)
      assert.match(html, /no clear improvement in warning accuracy/)
      assert.match(html, /historical charts describe the original Random Forest/)
    })
    await t.test('an unavailable candidate is disabled in the selector', () => {
      const context = { modelProfile: 'original', setModelProfile: () => {}, optionsState: 'ready', options: [] }
      const html = renderToStaticMarkup(React.createElement(ModelProfileContext.Provider, { value: context }, React.createElement(MemoryRouter, null, React.createElement(Header))))
      assert.match(html, /value="calibrated" disabled=""/)
      assert.match(html, /unavailable/)
    })
    await t.test('sidebar uses the selected model family', () => {
      for (const modelProfile of ['original', 'calibrated']) {
        const html = renderToStaticMarkup(React.createElement(ModelProfileContext.Provider, { value: { modelProfile } },
          React.createElement(MemoryRouter, null, React.createElement(Sidebar))))
        assert.match(html, modelProfile === 'calibrated' ? /Calibrated Random Forest V3/ : /Random Forest V2/)
        if (modelProfile === 'calibrated') assert.doesNotMatch(html, /Random Forest V2/)
      }
    })
    await t.test('experiment view shows actual detection, survivor burden and separate WATCH counts', () => {
      const report = JSON.parse(readFileSync(new URL('../src/data/recallExperiments.json', import.meta.url), 'utf8'))
      for (const modelProfile of ['original', 'calibrated']) {
        const html = renderToStaticMarkup(React.createElement(ModelProfileContext.Provider, { value: { modelProfile } },
          React.createElement(RecallExperiments, { report })))
        const rows = report.models[modelProfile === 'calibrated' ? 'calibrated' : 'raw']
        for (const row of rows) {
          assert.ok(html.includes(`${row.any_warning.tp} / 354`))
          assert.ok(html.includes(`${row.any_warning.fp} / 2200`))
          assert.ok(html.includes(`${(row.any_warning.recall_in_assessed_population * 100).toFixed(1)}%`))
        }
        assert.match(html, /Death labels with WATCH only/)
        assert.match(html, /separate five-checkpoint candidate now uses its own training-selected 85% target/)
        assert.match(html, /not an individual patient/)
      }
    })
    await t.test('new candidate comparison keeps model choice and validation results distinct', () => {
      const report = JSON.parse(readFileSync(new URL('../src/data/modelImprovements.json', import.meta.url), 'utf8'))
      const html = renderToStaticMarkup(React.createElement(ModelImprovements, { report }))
      for (const candidate of report.candidates) {
        assert.ok(html.includes(candidate.label))
        assert.ok(html.includes(`${candidate.any_warning.tp} / ${report.death_labels}`))
        assert.ok(html.includes(`${candidate.any_warning.fp} / 2200`))
      }
      assert.match(html, /training patients only/)
      assert.match(html, /existing saved models/)
      assert.match(html, /not an independently tested score/)
      assert.match(html, report.research_promotion_gate.passed ? /met this check/ : /did not meet both requirements/)
    })
    await t.test('focused study shows both grids and keeps training choice separate from queue models', () => {
      const report = JSON.parse(readFileSync(new URL('../src/data/forestTuning.json', import.meta.url), 'utf8'))
      const html = renderToStaticMarkup(React.createElement(ForestTuning, { report }))
      for (const [id, candidate] of Object.entries(report.candidate_definitions)) {
        assert.ok(html.includes(candidate.label))
        for (const grid of ['coarse', 'fine']) {
          const counts = report.results[grid][id].any_warning
          assert.ok(html.includes(`${counts.tp} / ${report.death_labels}`))
          assert.ok(html.includes(`${counts.fp} / ${counts.fp + counts.tn}`))
        }
      }
      assert.match(html, /same predictions/)
      assert.match(html, /training patients only/)
      assert.match(html, /0\.001/)
      assert.match(html, /keeps its existing saved models and thresholds/)
      assert.match(html, /not an untouched final test/)
      assert.match(html, report.research_promotion_gate.passed ? /met this check/ : /did not meet all requirements/)
    })
    await t.test('replay controls clearly show recorded time and disable play before data arrives', () => {
      const state = { minutes: 0, patient: null, loading: true, playing: false,
        completed: false, error: null, requestedMinutes: 0, step: 60 }
      const html = renderToStaticMarkup(React.createElement(RecordedReplayControls, { state, session: {} }))
      assert.match(html, /00:00/)
      assert.match(html, /not a live hospital feed/)
      assert.match(html, /Scores appear at 6h, 12h, 24h only/)
      assert.match(html, /<button[^>]*disabled=""[^>]*>Play replay/)
      assert.match(html, /<button[^>]*disabled=""[^>]*>Pause replay/)
      assert.match(html, /Reset to admission/)
      const playing = renderToStaticMarkup(React.createElement(RecordedReplayControls, {
        state: { ...state, patient: {}, loading: false, playing: true, minutes: 375 }, session: {},
      }))
      assert.match(playing, /06:15/)
      assert.match(playing, /Replay time 06:15/)
      assert.match(playing, /Playing recorded data/)
      assert.doesNotMatch(playing, /disabled=""[^>]*>Pause replay/)
    })
    await t.test('patient page keeps replay optional and closed on first opening', () => {
      const html = renderToStaticMarkup(React.createElement(ModelProfileContext.Provider, { value: { modelProfile: 'original' } },
        React.createElement(MemoryRouter, { initialEntries: ['/patients/ICU-1003'] },
          React.createElement(Routes, null, React.createElement(Route, {
            path: '/patients/:patientId', element: React.createElement(PatientDetails),
          })))))
      assert.match(html, /Optional demo: replay recorded observations/)
      assert.match(html, /<details class="replay-demo-disclosure">/)
      assert.doesNotMatch(html, /<details[^>]*open/)
    })
  } finally {
    await server.close()
  }
})

test('role screens show the five agreed roles and appropriate navigation', async (t) => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false } })
  try {
    const { AuthContext } = await server.ssrLoadModule('/src/context/Auth.jsx')
    const { default: Sidebar } = await server.ssrLoadModule('/src/components/layout/Sidebar.jsx')
    const { default: Login } = await server.ssrLoadModule('/src/pages/Login.jsx')
    const { default: TeamAccounts } = await server.ssrLoadModule('/src/pages/TeamAccounts.jsx')
    const { default: Account } = await server.ssrLoadModule('/src/pages/Account.jsx')
    const { UsernameField } = await server.ssrLoadModule('/src/components/AccountFields.jsx')
    const { default: Register } = await server.ssrLoadModule('/src/pages/Register.jsx')
    const { default: PermissionRequests, ReviewedRequestRow } = await server.ssrLoadModule('/src/pages/PermissionRequests.jsx')
    const { default: PatientTeam } = await server.ssrLoadModule('/src/components/PatientTeam.jsx')
    const { default: RequestNotice } = await server.ssrLoadModule('/src/components/RequestNotice.jsx')
    const { default: Recover } = await server.ssrLoadModule('/src/pages/Recover.jsx')
    const { default: AccountRecovery } = await server.ssrLoadModule('/src/components/AccountRecovery.jsx')
    const { RequestNotificationContext } = await server.ssrLoadModule('/src/context/RequestNotifications.jsx')
    const user = { id: 1, display_name: 'Test User', username: 'test-user', active: true,
      preferences: { preferred_model: 'expanded', page_size: 50, replay_step: 180 } }
    const render = (component, value) => renderToStaticMarkup(React.createElement(AuthContext.Provider, { value }, React.createElement(MemoryRouter, null, React.createElement(component))))
    for (const role of ['admin', 'doctor', 'nurse', 'coordinator', 'researcher']) {
      await t.test(`${role} has only its intended navigation`, () => {
        const html = render(Sidebar, { user: { ...user, role } })
        assert.equal(html.includes('aria-label="Patient Queue"'), role !== 'researcher')
        assert.equal(html.includes('aria-label="Team Accounts"'), role === 'admin')
        assert.equal(html.includes('aria-label="Account Requests"'), role === 'admin')
        assert.ok(html.includes('My Account') && html.includes('Model Performance'))
      })
    }
    await t.test('first setup asks the owner to create credentials and contains no default password', () => {
      const html = render(Login, { loading: false, setupRequired: true })
      assert.match(html, /Create administrator account/)
      assert.match(html, /minLength="15"|minlength="15"/)
      assert.match(html, /Confirm password/)
      for (const input of html.match(/<input\b[^>]*>/g) || []) {
        if (/name="(?:password|confirmation)"/.test(input)) assert.doesNotMatch(input, /value="[^"]+"/)
      }
      assert.match(html, /Start with a lowercase letter/)
      assert.match(html, /aria-label="Show password"/)
      assert.match(html, /aria-label="Show confirm password"/)
      assert.equal((html.match(/type="password"/g) || []).length, 2)
      assert.equal((html.match(/type="button"/g) || []).length, 2)
    })
    await t.test('duplicate warning is attached to the username and sign-in has its own eye button', () => {
      const html = renderToStaticMarkup(React.createElement(UsernameField, { error: 'That username is already in use. Choose another username.' }))
      assert.match(html, /aria-invalid="true"/)
      assert.match(html, /role="alert"/)
      assert.match(html, /already in use/)
      const login = render(Login, { loading: false, setupRequired: false })
      assert.match(login, /aria-label="Show password"/)
      assert.doesNotMatch(login, /Confirm password/)
    })
    await t.test('workers request access while team accounts only manage approved users', () => {
      const html = render(TeamAccounts, { user: { ...user, role: 'admin' } })
      assert.match(html, /Workers request their own accounts/)
      assert.doesNotMatch(html, /Create team account/)
      const signup = render(Register, {})
      for (const role of ['doctor', 'nurse', 'coordinator', 'researcher']) assert.ok(signup.includes(`value="${role}"`))
      assert.doesNotMatch(signup, /value="admin"/)
      assert.match(signup, /administrator must verify and approve/)
      assert.match(signup, /aria-label="Show password"/)
      assert.match(signup, /aria-label="Show confirm password"/)
      const requests = render(PermissionRequests, {})
      assert.match(requests, /Approval creates their account; rejection does not/)
      assert.match(requests, /Pending/)
      assert.match(requests, /Approved/)
      assert.match(requests, /Rejected/)
      const settings = render(Account, { user: { ...user, role: 'doctor' } })
      assert.match(settings, /value="expanded" selected=""/)
      assert.match(settings, /value="50" selected=""/)
      assert.match(settings, /value="180" selected=""/)
    })
    await t.test('password forms require confirmation and recovery is not offered for self or disabled accounts', () => {
      const recovery = render(Recover, {})
      assert.match(recovery, /expire after 15 minutes/)
      assert.match(recovery, /Confirm new password/)
      assert.match(recovery, /name="recovery_code"/)
      assert.match(recovery, /aria-label="Show new password"/)
      assert.doesNotMatch(recovery, /value="[A-Za-z0-9_-]{43}"/)
      const settings = render(Account, { user: { ...user, role: 'nurse' } })
      assert.match(settings, /Current password/); assert.match(settings, /Confirm new password/)
      const target = { ...user, id: 2, role: 'doctor' }
      const props = { currentId: 1, account: target }
      assert.match(renderToStaticMarkup(React.createElement(AccountRecovery, props)), /Password recovery for/)
      assert.equal(renderToStaticMarkup(React.createElement(AccountRecovery, { ...props, currentId: 2 })), '')
      assert.equal(renderToStaticMarkup(React.createElement(AccountRecovery, { ...props, account: { ...target, active: false } })), '')
    })
    await t.test('doctor and nurse groups separate assigned staff and expose editing only to unit managers', () => {
      const assignments = [{ id: 2, display_name: 'Doctor One', username: 'doctor1', role: 'doctor', active: true },
        { id: 3, display_name: 'Nurse One', username: 'nurse1', role: 'nurse', active: false }]
      const html = renderToStaticMarkup(React.createElement(PatientTeam, { assignments, staff: [], canEdit: true, patientId: 'ICU-1002' }))
      assert.match(html, /<summary>Doctors/); assert.match(html, /<summary>Nurses/)
      assert.ok(html.indexOf('Doctor One') < html.indexOf('<summary>Nurses'))
      assert.ok(html.indexOf('Nurse One') > html.indexOf('<summary>Nurses'))
      assert.match(html, /Inactive account/); assert.match(html, /Edit doctors/); assert.match(html, /Edit nurses/)
      const readonly = renderToStaticMarkup(React.createElement(PatientTeam, { assignments, staff: [], canEdit: false }))
      assert.doesNotMatch(readonly, /Edit doctors|Edit nurses/)
    })
    await t.test('reviewed requests are compact and extra details start closed', () => {
      const html = renderToStaticMarkup(React.createElement(ReviewedRequestRow, { request: {
        id: 1, username: 'doctor1', display_name: 'Worker', requested_role: 'nurse', granted_role: 'doctor',
        status: 'approved', created_at: 1800000000, reviewed_at: 1800000001, reviewed_by: 1, review_note: 'Verified', request_note: 'ICU',
      } }))
      assert.match(html, /reviewed-request-summary/); assert.match(html, /Granted role/)
      assert.match(html, /View details for doctor1/); assert.doesNotMatch(html, /<details[^>]*open/)
      assert.doesNotMatch(html, /Role to grant|textarea/)
    })
    await t.test('request popup offers view and dismiss actions with a matching sidebar count', () => {
      const value = { notice: { latestId: 12 }, pendingCount: 2, dismiss: () => {} }
      const html = renderToStaticMarkup(React.createElement(RequestNotificationContext.Provider, { value },
        React.createElement(AuthContext.Provider, { value: { user: { ...user, role: 'admin' } } },
          React.createElement(MemoryRouter, null, React.createElement(RequestNotice), React.createElement(Sidebar)))))
      assert.match(html, /New account request received/); assert.match(html, /2 pending account requests/)
      assert.match(html, /View requests/); assert.match(html, /Dismiss/)
      assert.match(html, /class="request-count"/)
    })
  } finally { await server.close() }
})
