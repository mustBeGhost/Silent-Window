# Optional historical replay

Replay shows an existing patient's recorded readings in time order. It is a
demonstration and testing tool. It does not improve model accuracy, collect
new readings, or connect to hospital equipment.

The patient page still opens the available 24-hour view. Its main assessment
comes first. Replay is in a closed, optional section below the main assessment.

## Use the demo

1. Open a patient and expand **Optional demo: replay recorded observations**.
2. Choose **Replay from start** to return to admission and begin playback.
3. Use **Pause replay** to inspect a view, or **Reset to admission** to start over.
4. Choose 15 minutes, one hour, or three hours per step. Each completed response
   is followed by a one-second delay, so request time affects playback speed.
5. The recorded-time selector jumps to admission, 6h, 8h, 12h or 24h and pauses.
   The five-checkpoint research option also offers 9h and 18h.

Readings are revealed only after their recorded timestamps. Assessments appear
at the selected model's checkpoints when usable observations exist: 6h/12h/24h
for original and V3; 6h/9h/12h/18h/24h for the new V4 research option. Even the fastest speed
visits each checkpoint. These are assessment times, not predictions of what
will happen in the next six, twelve, or twenty-four hours. The main score remains
the 12h assessment, including after the replay reaches 24h.

Closing the demo or hiding the tab pauses it. Reaching 24h stops automatically.
Changing patients or model versions cancels the old session and opens a fresh
24-hour view with the optional demo closed. Replay does not resume itself.

## Time and request safeguards

- Every view requests the existing patient-detail endpoint with an integer
  `as_of_minutes` between 0 and 1440 and the selected model profile.
- The replay does not fetch the full future record for later client-side filtering.
  Starting/resetting removes any previously displayed later view before loading
  admission data. The browser rejects responses for the wrong time or identity.
- The clock advances with a successful response. While the next step loads, the
  previous received view and its time remain visible. No additional step is queued.
- Pause cancels pending advancement and ignores late responses, even when a
  transport does not honor cancellation. A pending admission/manual view may
  finish at its chosen time while paused; it cannot start playback.
- A request error stops playback. The last received view, if present, is explicitly
  retained. Retry loads the failed time and stays paused.
- Missing readings stay missing; unavailable assessments have no fabricated score
  or alert. No new measurement values or continuous hourly model scores are created.

The replay checks cover stale responses, reset, pause, checkpoint boundaries,
completion and retry. Replay does not change training data or saved thresholds.
