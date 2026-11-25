# Character Profiles and Application Identity

The desktop application is a character-capable AI client. Its product identity is configured independently in `kira/config.py`:

- `APP_NAME`: product, window, and tray name.
- `PROJECT_URL` and `RELEASES_URL`: official source and update destination.
- `VERSION`: displayed application version.

The active character is selected by profile ID. Kira is the built-in starter profile, not the application's identity, a Provider, or a model. Character data lives in `kira/characters/kira.py`; the generic profile registry lives in `kira/characters/registry.py`.

## UI sections

- **Chat:** current conversation and selected character.
- **Characters:** select, create, edit, and remove profiles. The built-in Kira profile cannot be deleted.
- **Voice:** shared speech input/output settings. The selected character's wake phrase follows its profile name; Kira retains legacy wake aliases. TTS voice/rate/pitch are application-wide settings, not independent per-character settings.
- **Personality:** baseline behavioral traits for the active profile.
- **Preferences:** language, appearance, desktop companion, and general behavior.
- **Route:** providers, models, priorities, failover, and local Ollama tuning.
- **Help:** current app version, release page, repository, and about information.

## Data ownership

Profile files live under the external application data directory in `characters/profiles.json`. Character-specific emotional state, relationship state, learned trait adjustments, and voice-style samples live under `characters/<profile-id>/`. Kira retains its existing legacy mood and voice-memory files so upgrades do not discard stored state.

User facts, dated events, conversation summaries, and the evidence index remain shared application memory. This allows each character to use the same user-provided facts without copying or conflating their individual speaking styles. Chat history is currently shared as well.

Desktop companion artwork and TTS voice selection remain shared UI settings; per-character avatar and voice selection are not yet implemented. The Provider/Router layer does not depend on the selected character. A profile supplies identity, description, notes, and baseline traits to the shared prompt and decision engines; it does not choose the model or Provider.

Every character receives the same shared capability contract: the same routed model, tool registry and permissions, planner, task modes, memory/context access, safety rules, reasoning quality bar, and result-verification requirements. A profile may change only conversational expression (tone, temperament, humor, warmth, assertiveness, emotional style, and relationship style). It cannot add or remove tools, change the model, bypass confirmations, or lower task quality. This is enforced by one shared ToolAgent and HybridRouter instance in the application, not only by prompt wording.

## Add another profile

Use **Characters → New character**. Enter a name, description, and character-specific notes, then use **Personality** to set baseline traits. The new profile's emotional state and voice-style samples are stored separately from Kira's.
