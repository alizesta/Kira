# Startup and Memory Measurements

Kira appends one JSON record when the process reaches the first Qt event-loop tick.

## Location

`DATA_DIR/logs/startup-performance.jsonl`

The file is append-only JSON Lines. It contains process diagnostics only. Prompts, message text, provider credentials, private user data and chat history are not recorded.

## Record schema

- `schema_version`: metrics schema version (currently 2).
- `recorded_at`: local timezone-aware timestamp.
- `phases`: cumulative `elapsed_ms` and incremental `since_previous_ms` per startup phase.
- `total_ms`: cumulative time through the last recorded phase, normally `event_loop_first_tick`.
- `memory_samples`: process-memory snapshots at startup phases. On Windows: `working_set_mb`, `peak_working_set_mb` and `private_bytes_mb`. On supported non-Windows systems: `peak_rss_mb`.

The timeline includes import, settings and module initialization, UI composition, window display and the first event-loop tick.

## Collecting a baseline

1. Launch the updated Windows build normally, wait until the chat window is interactive, then close Kira cleanly.
2. Repeat for at least five fresh launches under the same machine/profile conditions.
3. Compare medians for `window_shown.elapsed_ms` and `event_loop_first_tick.elapsed_ms`, and compare `working_set_mb` / `private_bytes_mb` at those phases. Keep peak working set as a separate high-water mark.
4. Compare before/after records from the same PC, data directory and build configuration. Exclude runs performing model downloads or first-time setup.

The code change adds measurement instrumentation; it does not claim a measured speedup or RAM reduction. No target-Windows baseline was available while authoring this change. The application must be launched on the target machine to populate genuine samples.
