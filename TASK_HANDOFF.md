# Task Handoff

## Current task
Character specialization and generated portraits. The implementation is complete in source; verify the new portraits and role prompts in the Windows 11 UI. The earlier Ai1 Code phase 2 Windows validation remains outstanding.

## Branch
`feature/characters-ren-mika`

## Implemented in phase 2
- Code Agent can propose a complete replacement for the selected file only.
- Proposal parsing requires exact start/end markers, rejects empty output and enforces a 512 KiB model-output ceiling.
- Patch generation is blocked whenever the selected context contains redacted credentials.
- Workspace presents a read-only unified Diff and requires an explicit apply action.
- Apply is rejected if the file on disk or editor content changed after the proposal was created.
- Approved changes preserve a one-time `.ai1code.bak` backup and use a temporary sibling file followed by atomic replacement.
- Added tests for valid marker parsing and malformed/empty proposal rejection.

## What remains for user-side validation
1. Run the latest ZIP on Windows 11 and open Ai1 Code.
2. Select a small text/code file and ask for a simple one-file change.
3. Confirm the Diff is readable and rejecting the dialog leaves the file unchanged.
4. Generate another proposal, approve it, and confirm the file changes and the backup exists.
5. Modify the file externally after opening it; confirm stale Patch application is blocked.
6. Test PowerShell with a harmless read-only command and inspect output/exit code.
7. Capture any traceback or UI freeze. GUI/PySide6/PowerShell are not exercised by portable CI.

## Not implemented yet
- Multi-file coordinated patches and cross-file Diff.
- Automated test runner and test-result UI.
- Debugger and breakpoints.
- Git status/diff/commit controls.
- Windows runtime debugging based on the user's actual machine logs.


## Character specialization update
- Kira has a coding/software-development specialty prompt and directs project-file workflows to Ai1 Code without claiming tests or edits that did not happen.
- Mika specializes in medical information and health education with explicit no-diagnosis/no-prescribing boundaries, emergency escalation and health-data privacy.
- Ren specializes in current news and intelligence analysis with date checks, independent-source comparison and fact/claim/opinion separation.
- Character specialties do not alter shared model routes, tools, permissions or safety policy.
- Replaced built-in SVG placeholder portraits with generated anime JPEG portraits stored as base64 text assets under `assets/characters/`; the native Qt Characters tab decodes them for display.
- Portable regression tests cover the specialty prompts. Windows GUI image rendering still needs a user-side check.
