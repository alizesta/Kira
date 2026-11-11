# Task Handoff

## Current task
Implement manual Game Mode and optional game-window Vision capture in Ai1.

## Branch
`feature/characters-ren-mika`

## Implemented
- Added `kira/game_mode.py` for Windows foreground process/window detection and guarded capture.
- Added a 🎮 toggle to the chat toolbar.
- Game detection adds a suggestion to chat and optionally the system tray; it does not activate Game Mode.
- Suggestions are emitted once per detected process ID in the current app session.
- Game Mode starts disabled on each launch.
- When enabled, the last detected game window is captured and attached to the next user message through the existing image pipeline.
- Turning it off immediately disables further capture.
- Ai1 is the application name; Kira is a character name.

## Known limitations / test plan
- Detection is heuristic and may miss windowed games or suggest immersive non-game apps.
- Capture requires Windows and a valid visible game window.
- The selected chat Route must use a vision-capable model. Automatic vision-capability detection and route filtering are not implemented yet.
- Test on the user's Windows PC: launch a game, confirm one suggestion, confirm Game Mode stays off until clicked, send a gameplay question with Game Mode on, then switch it off and confirm later messages no longer include a screenshot.
- Confirm the selected model can accept image payloads and inspect actual screenshot content.
- Verify app startup, chat, and portable release workflow.
