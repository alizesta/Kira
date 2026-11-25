# Unified System Access Manager (T5-Core)

Code:

- `kira/tools/sysaccess.py` — central manager.
- `kira/tools/registry.py` — sole execution entry point, `execute()`.
- `kira/tools/wincontrol.py` — Windows capability declarations.
- `kira/tools/winrunner.py` — sole PowerShell runner.

Every tool—Windows (applications, Bluetooth, audio, desktop), files, web, MCP, and agents—passes through `ToolRegistry.execute()` and consults the central manager. No module has its own separate permission, confirmation, or journal system. A module only **declares** its access level, conditions, and backend; the central manager **enforces** them. The system is independent of Providers and models; the text protocol remains unchanged.

## Permission levels

| Level | Meaning | Confirmation |
|---|---|---|
| READ | Read-only operation | None |
| CONTROL | Ordinary, reversible application/Windows control (audio, windows, Bluetooth, typing into a window, opening an app) | None, but more sensitive actions require explicit intent in the same message (`intent_rx`) |
| FILE | Non-destructive file/folder management (create, copy, rename, append text) | Same as CONTROL; always constrained by PathPolicy |
| ELEVATED | Requires Administrator | Always; UAC confirmation is scoped to one operation (no current capability uses it) |
| PROTECTED | Sensitive, destructive, or irreversible operation (delete, overwrite, raw mouse click, clipboard read, delegate work to an agent) | Always |

Legacy tools remain registered. Their old `level` maps automatically: READ → READ, ACTION → FILE (for the files category) or CONTROL, SENSITIVE → PROTECTED. `windows_control_info` displays the complete tool table (level, domain, backend, conditions) and the latest real operation.

## Rules (enforced in code, not by trusting the model)

1. **Confirmation is bound to the exact operation and parameters.** The Agent creates a one-use Grant, valid for five minutes, only when the user's own message is a bare confirmation (confirm, yes, okay, do it, etc.). The Grant is bound to the same `(tool, arguments)` pair and is checked again by `execute()`. Stop revokes it.
2. **A confirmation message is not an execution request.** A message that names an action (“delete it”, “delete the other file”) is not treated as confirmation. The previous question is invalidated and the message is handled as a new request. “Cancel” or “No” cancels the operation.
3. **Explicit intent (`intent_rx`):** the current user message must request the operation. The model cannot initiate it by itself. This applies to Bluetooth, audio, desktop, files, web, and MCP; the earlier separate web guard has been moved here.
4. **Taint:** after external content is read in the same message (web, `read_file`, MCP/agent), any CONTROL/FILE action without its own explicit-intent guard (such as `open_url`, `open_app`, or `open_path`) requires confirmation. Text inside a page or document therefore cannot silently open something.
5. **Backend:** each operation declares its backend (`win32`, `uia`, `com`, `sendinput`, `powershell-fixed`, `winrt`, `filesystem`, `network`, or `external`). Alternate backends are chained through `Capability.fallbacks`. An unavailable backend raises `BackendUnavailable` and the next is tried; the backend actually used is recorded in the journal.
6. **No free-form PowerShell:** only `winrunner.FixedScript` is allowed (fixed source code, `-EncodedCommand`, and data passed through `KIRA_*` environment variables). Desktop UI Automation and Store-app discovery now use the same runner; `-ExecutionPolicy Bypass` was removed. Parameter names such as `command`, `script`, `shell`, `powershell`, and `cmd` are rejected at registration.
7. **Journal:** every call (allowed, rejected, waiting for confirmation, or failed) is recorded in memory with level, backend, arguments (private text is represented by length only), status, duration, and actual result. The journal is capped at 300 entries and is not written to disk. “Verified” means the handler read the actual state after changing it.
8. If an operation did not execute, the tool result is `error/denied`; the model sees that result. Success is never inferred from tool wording.

## Multi-step operations

Example: “Lower the game's volume and open Notepad.” One user turn can make up to three calls in a single round (`audio_list_apps` → `audio_change_app_volume` with automatic verification → `open_app`). Longer requests use the existing Planner/Task path (`autonomy.py`), which invokes the same `execute()` and the same policy. Each step has its own real result, and the final report describes both.

## Add a new module (Wallpaper / Tray / Wi-Fi / Display / Office, etc.)

1. Confirm that its domain exists in `DOMAINS` (`wincontrol.py`), or add one line.
2. Implement a `WinModule` with `domain` and `capabilities()`. Each `Capability` declares `permission` (or `risk`), `intent_rx` for CONTROL/FILE (or `intent_optout` with a reason), `confirm_summary` for ELEVATED/PROTECTED, `backend` and optional `fallbacks`, `verifies_result=True` when it reads back state, and `external=True` when its output is external content.
3. If a PowerShell script is required, declare `FixedScript(...)` at module scope and call `run_fixed(script, env={"KIRA_X": json})`.
4. Register the module in `builtin.py` with `layer.register_module(MyModule(...))`. A new presentation category requires one line in `protocol.GATES`.

Do not implement separate permission/confirmation/journal systems. Add a missing shared rule to `sysaccess.py` so every tool benefits.

## Integrated, removed, and remaining

- **Integrated:** explicit Bluetooth/audio/desktop guards in the layer (`_intent_ok`) and Registry (two implementations) → one central `check_intent`; web guard inside its handler → central policy (`intent_alt` for “continue research”); separate `OperationLog` in `WindowsControlLayer` → central journal for all tools; broad confirmation regex in Agent → bare confirmation plus Grant; separate desktop/Store PowerShell runners → `winrunner`.
- **Removed (duplicate mechanisms only):** `OperationLog` and `WindowsControlLayer.log/info_text/_intent_ok`, broad `CONFIRM_RX`, webtools' internal `_intent_ok`, and `-ExecutionPolicy Bypass`. No user-facing capability was removed.
- **Unchanged:** Audio, Bluetooth, Desktop, File Agent, App Launch, Web, MCP, and Hybrid Brain; PathPolicy (central sensitive-path and secret policy); and domain-specific guards (blocked windows and dangerous controls in desktop), which are domain rules rather than permissions.

## Limitations and Windows 11 validation

- The original handoff recorded no runtime test/execution; only Python syntax (`py_compile`) was checked. All behavior requires Windows 11 validation, especially Grant order in multi-step tasks, Taint after `web_*`/`read_file`, and UIA/Store execution through `run_fixed` (the output must be one single-line JSON object).
- **ELEVATED is policy only:** mandatory confirmation, labels, and journal support exist, but one-operation UAC handling (ShellExecute `runas` with a fixed script) was not implemented because no current capability needs it. Add and validate it on Windows 11 when the first Administrator-only capability is introduced.
- Raw `ToolRegistry` (development/unit-test entry point) still accepts `confirmed=True` from its caller. Only `ToolAgent` (the real app path) enforces Grants through `access.require_grants`. Legacy tests that call `confirmed=True` directly retain that behavior.
- Taint may require an additional confirmation for “search and open the first link”; this is intentional.
- The journal is memory-only; permanent persistence is deliberately not implemented.
- Wi-Fi, brightness, Wallpaper, Tray, device management, Word/Office, and full Clipboard operations were not implemented in this task. The extension path is prepared only.
