# Computer Awareness and Tool System (Stage 1)

> Multi-step planning, automatic execution, and task management are built on this foundation; see `docs/AGENT.md`.

Kira can read live Windows information and execute controlled tools. The model has no unrestricted shell.

## How it works

1. In `auto` mode, the model decides during the main request whether the message is ordinary conversation or needs a tool. When a message has no recognized task signal, the model receives only a compact **capability list** (tool names in a few lines, without parameters). Ordinary conversation can finish in that one small call. If the work needs the PC or internet, using any wording—even unfamiliar wording—the model emits an internal `use_tools` block and is run again in the same turn with the full catalog and Planner. The user never sees this block, and nothing executes during the first stage. The Planner can see local and read-only web tool catalogs (desktop, applications, files, system, audio, and web) so new or unfamiliar requests are not missed because of unknown keywords. Web rules still allow search only on explicit user request. External MCP/Agent tools are added only when explicitly named in the request.
2. If a tool is required, the model writes one block such as `<kira_tool>{"tool":"get_datetime","args":{}}</kira_tool>`. The user does not see the block.
3. The application executes the tool and returns the **actual result** to the model. Kira writes the final answer in her usual voice. Up to four consecutive tool rounds may be used.
4. The text protocol works with all Providers and local models; Function Calling is not required. The same call is not executed twice within one user message. If a tool fails, the actual error reaches the model and user. If the model fails after tool execution, the actual tool result is still shown to the user.

## Deterministic Fast Path

For exact, one-step commands, Kira uses a deterministic parser before calling the model. When a high-confidence exact match is found, it calls the tool directly and skips the model round trip.

Supported commands include time/date, Bluetooth, system volume, opening applications, system information, RAM/CPU/GPU/battery usage, disk space, network/local IP status, running-application list, and active window.

Fast Path is only a shortcut for request recognition. Tool execution still goes through **ToolRegistry** and all existing controls: Tools mode, permission level, Access Manager, and Competitive Safe restrictions. Sensitive operations, external tools, multi-request messages, and ambiguous wording do not enter Fast Path; they use the normal model route. The parser is not general semantic understanding; it accepts only precise, high-confidence patterns.

### Fast Path boundaries and completion status

Fast Path has five defined stages:

1. **Deterministic parser:** converts only one short, one-step, high-confidence request into a tool name and arguments. If there is no exact match, parser output is None.
2. **Expand bounded command coverage:** read-only system queries (specifications, resource usage, disks, network, and open windows) were added to the allowlist. This does not add free-form or chained commands.
3. **Harden dispatch:** complex decisions or continuing tasks take priority in Planner over Fast Path. The tool must exist in Registry, be internal and non-sensitive, and the parser category must match the actual tool and application.
4. **Test the real execution boundary:** tests cover ToolAgent → real ToolRegistry; success and rejection journal entries; changing `tools_mode` after planning; cancelling a pending plan with Competitive Safe; runtime security-guard rejection; and preventing repeated execution of the same call.
5. **Documentation and operational acceptance:** dispatch contract, safe execution path, test command, and Windows checklist are documented. Completing documentation is not runtime acceptance.

**Definitive rule:** Fast Path has no separate system-execution mechanism. It creates one bounded tool call; `ToolRegistry.execute()` is the final authority for validation, permission, execution guard, handler execution, and result recording. A security-state change after planning must therefore still take effect at execution time.

**Real-boundary test coverage (Stage 4):**

In `tests/test_fast_commands.py`, `FastPathRealRegistryBoundaryTests` uses the real `ToolRegistry` and `AccessManager`; only the model Router is stubbed so that any model call fails the test immediately. Coverage includes successful execution and journal recording, rejection after Tools mode is disabled, cancellation of a pending plan by Competitive Safe, runtime-guard rejection and journaling, and prevention of duplicate journal/execution when a cached result is returned. It also verifies that cache scope is limited to the same turn and the same request can execute on a later turn; cancellation before dispatch must create no journal entry. These are software-boundary integration tests, not a substitute for the full unittest suite or Windows runtime testing.

Focused test command:

```powershell
python -m unittest discover -s tests -p "test_fast_commands.py" -v
```

**Windows acceptance checklist:**

- A read-only command such as “What are my system specs?” must execute without a model call and return real data.
- An exact command such as “Set volume to 50 percent” must go through Registry and report the tool's actual result.
- Ambiguous or multi-step wording must not use Fast Path.
- Disabling tools or enabling Competitive Safe between Plan and Run must stop that Plan.
- The same call must not execute the handler twice in one turn.

Current status: focused tests and execution boundaries have been added to source, but until unittest and Windows runtime checks actually run, Fast Path is not runtime-accepted. GitHub Actions is not part of this acceptance criterion.

## Tools and permission levels

**Level 1 — Read-only (runs on user request)**

`get_datetime` (time, Gregorian/Solar Hijri date, time zone) · `get_system_info` (Windows version, language, CPU, RAM, GPU) · `get_resource_usage` (CPU, RAM, NVIDIA GPU, battery) · `get_disks` · `get_network_info` · `list_running_apps` · `get_active_window` · `find_app` · `list_allowed_folders` · `search_files` · `list_folder` · `file_info` · `read_file` (text/code/CSV/JSON, DOCX, PDF).

**Web tools (Level 1, read-only, explicit request required)**

`web_search` · `web_read` · `web_research` · `web_research_status`. Full guide and security rules: `docs/WEB_RESEARCH.md`.

**Level 2 — Ordinary operations**

`open_app` (Start Menu apps, Steam games/apps, installed Windows apps, Store apps, and a small set of fixed Windows utilities; activates an existing instance and reports the observed result — `docs/APP_LAUNCH.md`) · `open_path` (open a file with its default app or a folder in Explorer; **never** executes an application/script/shortcut) · `open_url` (HTTP/HTTPS only).

**Level 3 — Sensitive (always requires explicit confirmation)**

`delete_file` (one file only, to the Recycle Bin; reversible) · `move_file` (does not overwrite). The model does not execute these directly: Kira explains exactly what will happen and the user must type “Confirm” (or “Cancel”). Confirmation is valid for five minutes and applies to the stored arguments. Sending another message invalidates the previous request.

Installing/uninstalling applications, administrative commands, changing Windows settings, and shell execution are **not available** in this version.

## File access

- **Allowed:** the Windows user's Desktop, Documents, Downloads, Pictures, Videos, and Music folders (even when redirected to another drive or OneDrive), plus folders explicitly added by the user.
- **Always blocked:** Kira's own data folder (settings, keys, conversations), AppData, Windows and Program Files, `.ssh` and similar folders, and files/folders whose names resemble secrets/keys (`.env`, `*.pem`, `password`, and similar).
- Paths are fully resolved first; symlinks and `..` cannot escape the permitted roots.
- Keys and tokens that look like API keys are redacted before reaching the model.
- **Privacy note:** file content the user asks Kira to read is sent to the active model. With a cloud model, that means it is sent to that service. Use a local Ollama model for private files.

## Settings (in `settings.json` beside user data)

| Key | Default | Meaning |
|---|---|---|
| `tools_mode` | `auto` | `auto` lets the model decide when a tool is needed; `always` always exposes tools; `off` disables tools and retains only simple legacy shortcuts (Notepad, Calculator, etc.) |
| `tools_allowed_paths` | `[]` | Additional folders, for example `["D:\\Projects"]` |
| `tools_max_rounds` | `4` | Maximum tool rounds in one reply (1–6) |

## Memory

Tool results are **not** stored in conversation history or Kira's long-term memory. A few short notes (such as paths to files just found) are retained for up to 30 minutes in the current application run so the user can say “open the one you found” without repeating the entire request. They are cleared when the app closes. Only Kira's final answer is stored in conversation history as usual.

## Examples

- “What time is it?” → reads the Windows clock; it does not open the Clock app.
- “How much RAM is being used?” → reports current usage and available RAM.
- “Open Discord” → finds it in the Start Menu, launches or foregrounds it, and reports the observed result. If the name is ambiguous, Kira asks.
- “Find yesterday's PDF” → searches permitted folders and returns a list.
- “Delete this file” → asks for confirmation; after confirmation it goes to the Recycle Bin.

## Current limitations

- GPU utilization is available only for NVIDIA cards (using `nvidia-smi`); other cards report only the model name.
- “The app I'm using”: while talking to Kira, her own window is in the foreground; the highest other window in the window order is reported as a guess.
- `open_app` discovers Start Menu apps, Steam, Windows Installed Apps, and Store apps. Portable apps without installation metadata may not be found. Launch is reported only when a window/process is observed.
- File search has an 8-second and 40,000-item limit and reports when results may be incomplete. Scanned PDFs without text are not readable. PDF reading requires `pypdf`.
- Deletion is file-only, not folder deletion. Full Windows control, app installation/removal, autonomous permanent background operation, and Game Mode are deliberately not implemented; the architecture is ready for extensions (a new tool requires one function and one registration line in `kira/tools/builtin.py`).

## Developer map

`kira/tools/`:

- `registry.py`: tool definition, validation, and execution.
- `access.py`: file-path boundary.
- `sysinfo.py`, `fileops.py`, `apps.py`: tool implementations.
- `builtin.py`: tool registration.
- `protocol.py`: text protocol and stream filter.
- `agent.py`: tool loop on HybridRouter.

Every tool provides `json_schema()` so a native Function Calling adapter can be added later.

## Windows Bluetooth (`bluetooth_status` · `bluetooth_on` · `bluetooth_off`)

- **Implementation:** official Windows Runtime API (`Windows.Devices.Radios.Radio`: access, radio enumeration, `SetStateAsync`) through Windows PowerShell 5.1 and one **fixed** script. No user/model text is inserted into the script; only one of three fixed operations (read/On/Off) is selected. No additional package is required.
- **States:** on, off, disabled by the system (airplane mode/hardware switch), adapter not found, access error (`Let apps control radios` under Settings → Privacy), or unknown with the actual error cause. The `bthserv` service state is also reported.
- **Read-back verification:** after turning Bluetooth on/off, state is read again for up to 6 seconds. If the requested state is not reached, the tool returns failure with the real state and reason; it does not claim success. If it is already in the requested state, no change is made and that is reported.
- **Explicit request only:** state-changing tools have no input parameters and run only when the current user message mentions both Bluetooth and On/Off. Otherwise they are rejected, even if the model requests them. A short “do it” without mentioning Bluetooth is rejected.
- **Limitations:** Windows 10/11 with PowerShell 5.1 (`powershell.exe`) only. This API cannot override airplane mode, a hardware switch, or a disabled adapter in Device Manager. Device connection/pairing is not implemented. The original note says it was not tested on real Windows.
- **Examples:** “Turn Bluetooth on”, “Is my Bluetooth on?”, “Turn Bluetooth off”.

## Windows Audio (Audio Manager)

Volume, mute, per-app volume, device listing, and default input/output selection use the `audio_*` tools. Changes run only when explicitly requested in the same user message and are read back from Windows afterward. Guide: `docs/AUDIO_MANAGER.md`.

> **Central access control (T5-Core):** READ / CONTROL / FILE / ELEVATED / PROTECTED levels, confirmation bound to the same operation and arguments, explicit-intent guard, journal, and backends are documented in `docs/SYSTEM_ACCESS.md`.

## Replacement of word-based planning

The old method of counting verbs and language patterns to decide task complexity has been removed from the main execution path. `planner.assess()` remains only for compatibility with older callers and is not used for production decisions. Deciding whether a request needs a tool and constructing task steps happen through the model-driven Planner path. Exact one-step commands still use Fast Path.

## Semantic planning and evidence-based task evaluation

In automatic planning mode, requests with tool intent (except exact Fast Path commands) are not classified directly by verb counts or a per-task phrase list. The model sees the user's goal and the full local tool catalog and decides whether a simple answer is enough or a multi-step plan is needed. External MCP/Agent tools are still exposed only with explicit intent.

After each successful tool execution, a step first becomes **pending evaluation**, not **completed**. The model must compare the actual output with the goal and step completion condition and report the result in a structured block. A precise quotation from the actual tool output is required to confirm success, and code checks that the evidence is present. If the output only confirms that an input was sent or does not prove the final state, the model must mark the result uncertain, observe the state again, or change its plan. Pending-evaluation steps remain unconfirmed after restart and require fresh observation before an operation is repeated.

Fast Path is retained only for exact one-step commands. Permission levels, confirmation for sensitive operations, ToolRegistry, and Competitive Safe remain the final execution authority.

Each task plan stores not only a step title but also the final success criteria and an observable postcondition for every step. These criteria are persisted as task data and supplied to the model during later reviews, so success checking does not depend on a tool name or one particular verb.

After all tool steps finish, a separate final review checks the task's completion criteria. It must provide exact evidence from actual tool outputs for each criterion. Otherwise the task is not marked complete; the model must add an observation/action step or report the limitation explicitly. If the application closes mid-task, evidence that existed only in memory is not trusted and the current state must be observed again.

To validate the final goal, evidence is linked to each numbered success criterion; every quotation must appear exactly in a real tool output. External MCP/Agent tools stay hidden from the general planning catalog and are exposed only when the user explicitly mentions them in the request.
