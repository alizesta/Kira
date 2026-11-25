# Windows Control Layer

> **T5-Core:** Permission, confirmation, and journal decisions have moved to the central Access Manager; see `docs/SYSTEM_ACCESS.md`. This layer is now the place where Windows capabilities are **declared**. The actual-result and execution guards below are enforced by the central manager and central journal.

Code: `kira/tools/wincontrol.py` (core), `kira/tools/winmodules.py` (capability declarations), and `kira/tools/winrunner.py` (shared PowerShell runner). It uses the existing Tool Registry. Access Control, Level 3 confirmation, the text protocol, and Hybrid Brain continue unchanged. It is independent of Providers and models.

## Capability contract

Each `Capability` has a fixed name, fixed handler, closed and typed parameters, domain (`apps | bluetooth | audio | wallpaper | tray | system`), risk level, and execution condition. Registration validates the contract; an invalid declaration stops startup instead of creating a later hole.

| Level | Meaning | Condition |
|---|---|---|
| READ | Read-only | None |
| ACTION | Small, reversible change | `intent_rx` (explicit request in the **same** user message) or documented `intent_optout` |
| SENSITIVE | Sensitive operation | `confirm_summary` is required; Registry obtains explicit user confirmation before execution |

Command/script-like parameters (`command`, `script`, `shell`, `powershell`, `cmd`, `argv`, etc.) are rejected. No tool executes arbitrary text. PowerShell scripts are fixed and live inside modules.

Each capability declares `verifies_result` (read actual state after a change) and `changes_system`.

## Actual-result journal

Each execution is recorded in `OperationLog` in memory for the current run (maximum 200 entries; no disk persistence and no conversation-history entry). Records include domain, tool, level, status (ok/error/denied), duration, result summary, or error cause; keys are redacted. Rejection due to missing explicit intent is also logged.

The read-only `windows_control_info` tool displays the capability table and latest real operations (“What did you just do?”).

## Existing integration

Without rewriting underlying behavior, `AppsModule` (`find_app`, `open_app`) and `BluetoothModule` (`bluetooth_status/on/off`) declare their capabilities. Implementation in `apps.py`, `appcatalog.py`, and `bluetooth.py` is unchanged. Tool names, arguments, and model behavior remain unchanged. `open_path` and `open_url` remain in `builtin.py` for now because they belong closer to the file/web domains.

One guard moved: explicit Bluetooth intent is checked in this layer instead of Registry, and rejected attempts are recorded. Registry retains `intent_rx` for other tools.

## Audio module (Audio Manager) and shared runner

`AudioModule` in `winmodules.py` declares 11 audio capabilities; implementation is in `kira/tools/audio.py`. Full guide: `docs/AUDIO_MANAGER.md`.

**Shared runner (`winrunner.py`):** the only place that launches PowerShell. It accepts only `FixedScript` (fixed source defined in code at module import time); a normal `str` is rejected with `TypeError`. Variable data is never inserted into the script; it is passed only through `KIRA_*` environment variables and read as data by the script. The script runs through `-EncodedCommand` without a shell, and `powershell.exe` is resolved from System32.

The Bluetooth module delegates only its runner to this file (`bluetooth._run` returns the same output and error messages). Bluetooth logic and application launching were not rewritten.

## Add a new capability (Wallpaper / Tray / System)

1. Confirm that the domain already exists in `DOMAINS`; add one line if a new domain is needed.
2. Implement a `WinModule` with `domain` and `capabilities()`. The handler must return the actual result as text or raise `ToolError` with the actual cause. If PowerShell is required, use `winrunner.run_fixed` with a `FixedScript`.
3. Register it in `builtin.py`: `layer.register_module(WallpaperModule(...))`.
4. Add one line to `protocol.GATES` only when a new presentation category is required.

No Registry, Agent, or Hybrid Brain change should be needed.

## Limitations

- The original development note says the layer was not tested on real Windows; only syntax was checked. The Audio module has the same status; see `docs/AUDIO_MANAGER.md`.
- Journal is in-memory only and is cleared when the app closes (by design).
- Explicit-intent rejection is based on a regex over the current user message; a short message without the topic (such as “do it”) is rejected.
- The shared PowerShell runner (`winrunner.py`) was extracted and is used by Bluetooth and Audio.
