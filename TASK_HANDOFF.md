# Task Handoff

## Current task
Add MiniMax Global to Kira Cloud Voice.

## Branch
`feature/characters-ren-mika`

## Implemented
- Added MiniMax to the Cloud Voice provider registry and settings UI.
- Added Global API endpoint integration for T2A v2.
- Added built-in model catalogue: `speech-2.8-turbo`, `speech-2.8-hd`.
- Added a short Persian synthesis probe for API key validation.
- Added default voice ID `female-shaonv`; the existing editable voice field allows a custom Voice ID.
- Added speed control and basic mapping of cheerful/energetic/serious styles to MiniMax emotion values.
- Added regression tests and updated user documentation.

## Important limitations
- This first integration uses the synchronous HTTP TTS endpoint. It does not yet stream audio chunks directly to the player over WebSocket.
- MiniMax model IDs are a built-in catalogue, not an account-specific model discovery response.
- The validation probe consumes a small amount of TTS quota.
- Persian voice quality and the default voice ID still require a live test with the user's account.

## Verification still required
- Confirm the portable CI workflow succeeds and produces the timestamped ZIP.
- Test the user's own API key inside Kira.
- Compare Turbo and HD with Persian text.
- Evaluate WebSocket streaming and interruption separately; do not describe the current HTTP path as live audio streaming.
