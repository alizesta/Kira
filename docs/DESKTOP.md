# Desktop Interaction (T5-B)

Code: `kira/tools/desktop.py`, the `desktop` domain in the Windows Control Layer. No new dependency is required (ctypes plus one fixed PowerShell script for UI Automation).

## Tools

| Tool | Level | Function |
|---|---|---|
| `window_list`, `window_active` | READ | Open windows with `hwnd:N` identifiers and the active window |
| `window_focus` | 2 | Bring a window to the foreground and verify that it actually moved there |
| `window_close` | 2 | Request a graceful close (like clicking X); if the application asks whether to save, Kira does not claim it closed |
| `window_set_state` | 2 | Minimize, maximize, or restore, with a post-action check |
| `type_text` | 2 | Type up to 2,000 characters using Unicode SendInput (including Persian) |
| `press_keys` | 2 | Press one allowed key or shortcut (Enter, Tab, Esc, arrows, Ctrl+S/C/V/X/A/Z/Y/F, etc.) |
| `clipboard_set` | 2 | Set clipboard text and read it back for verification |
| `clipboard_get` | 3 (confirmation) | Read clipboard text; key/secret-like content is redacted |
| `ui_list_controls` | READ | List named buttons, menus, fields, and checkboxes in a window |
| `ui_click` | 2 | Invoke, toggle, select, or expand a named control |
| `ui_click_confirmed` | 3 (confirmation) | Same action for controls related to deletion, sending, payment, sign-in, installation, or permission |
| `ui_set_text` | 2 | Fill a text field through ValuePattern; read back and compare the value |
| `mouse_click` | 3 (confirmation) | Click a raw point inside a window, only when no named control is available |

## Safety rules (enforced in code)

- The target window is resolved from the user's wording (title, application name, “browser”, or `hwnd:N`). If multiple windows match, Kira asks for a more precise selection; it does not guess.
- **Before every input**, the target window is brought to the foreground and verified. Long text input rechecks every 40 characters and stops if the foreground window changes.
- Input is never sent to Kira itself, terminals/PowerShell/cmd/WSL, mshta/scripts, regedit/mmc/taskmgr, the Run dialog, UAC or Windows Security, windows whose titles indicate sign-in/password/authentication, or password managers. Typing into a terminal could execute an arbitrary command.
- The key list is closed: no Windows key, no Alt+F4 (use `window_close`), and no Ctrl+Alt+Del or Ctrl+Shift+Esc.
- Password fields (`IsPassword`) are never read or filled; text that resembles a key or secret is not typed.
- The UI Automation script is fixed. Inputs are passed as JSON through an environment variable, not interpolated into code.
- Typing, clicking, and key presses **cannot be automatically verified**; Kira must say so. Window close, window state, clipboard, and `ui_set_text` are read back after the operation.

## Limitations

- An application running as Administrator does not accept input from a non-elevated Kira process; the failure is reported.
- Some applications (games and applications with custom rendering) expose no UI Automation tree; only `mouse_click` may be available.
- Word creation and Office menu workflows are T5-C; audio and brightness are T5-D (audio controls already exist).

## Windows 11 validation still required

The original development note states that none of these checks had run in its environment:

1. Notepad: open it and type Persian text; verify correct text and right-to-left rendering.
2. Run `ui_list_controls` on Notepad and Calculator; use `ui_click` on buttons and `ui_set_text` on a search field.
3. Use `window_close` on Notepad with unsaved text; Kira must report that it remains open if the save prompt is present.
4. With two Chrome windows open, “close the browser” must require an `hwnd` selection.
5. Typing into PowerShell, Run, or a sign-in window must be rejected.
6. Measure UIA script execution on heavy windows (such as browsers); the limit is 20 seconds.
