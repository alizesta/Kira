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

## Current implementation status — 2026-11-23

Startup phase timing and process-memory sampling were integrated into `new-main` by PR #246. The JSONL record is emitted through the first Qt event-loop tick and includes the import, settings/module initialization, UI composition, window display and event-loop phases.

## Generating the five-launch report

After completing at least five clean launches on Windows, run the report utility from the repository root in PowerShell:

```powershell
python scripts\analyze_startup_performance.py "PATH_TO_DATA_DIR\logs\startup-performance.jsonl" --runs 5
```

Replace `PATH_TO_DATA_DIR` with the actual configured `DATA_DIR` from Kira's installation. The utility uses the latest five complete schema-v2 Windows records and prints the median, minimum and maximum for startup timings, Working Set, Private Bytes and Peak Working Set at both `window_shown` and `event_loop_first_tick`. It rejects an insufficient sample instead of reporting a misleading median, and skips malformed or incomplete records with counts.

The measurement protocol above is still required. At this snapshot no genuine target-Windows baseline has been accepted, and no before/after speedup or RAM reduction is claimed. Collect at least five comparable fresh launches from the same PC/build/profile and compare medians; keep Peak Working Set separate from the phase-specific Working Set and Private Bytes values.

Idle-avatar CPU is a separate measurement. A reduction from 30 to 5 scheduled animation callbacks per second must not be translated into an equivalent percentage reduction in total process CPU.
