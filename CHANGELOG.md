# Changelog

## 2026-11-21 (silent voice on Windows)
- `kira/voice.py`: on Windows, PCM `.wav` replies are now played with `winsound` (`_NativeWavPlayer`, volume applied to a temp copy, lip-sync/finish via duration timer) because Qt's QMediaPlayer reported success but stayed silent on the user's PC while Media Player played the same wav. Falls back to Qt for mp3/ogg, when a specific output device is chosen in settings, on any error, or if `voice_native_wav` is false. A chosen output device is ignored by the native path (it uses the Windows default).
- Not verified on Windows hardware (sandbox is Linux; unit test uses a fake winsound). 15 `test_voice_tts` failures are pre-existing.

## 2026-11-21 (dance library)
- New: `kira/dance_library.py` + folder `assets/vrm/animations/` (README inside). `.vrma` and Mixamo `.fbx` files are auto-detected; on music start the viewer plays a random clip (75%) or a built-in style, cross-faded, speed follows BPM. Rotations only, so she stays in place.
- `viewer.html`: `kiraDances`, VRMA/Mixamo retargeting, AnimationMixer evaluated after the procedural body. `vrm_vendor.OPTIONAL` fetches FBXLoader files best-effort (not required by `ready()`).
- Character tab: buttons "باز کردن پوشه‌ی رقص‌ها" and "دریافت رقص از Mixamo". Untested visually (needs Windows + real files).

## 2026-11-21 (desktop-pet behaviour, ideas from Mate Engine)

Mate Engine (shinyflvre) is a Unity/C# project under AGPL-3.0 + its own licence, so no code or assets were copied; only the behaviours were re-implemented for Kira's PySide6 + three.js VRM stack.

- **Hang from the cursor** (`kira/pet.py`, `viewer.html` `kiraHang`): while dragged she is held by the head, arms loose, knees bent, body swinging like a damped pendulum with the drag speed.
- **Fall and sit on windows / taskbar** (`kira/perch.py`, `kira/pet.py`): on release she falls with gravity and throw momentum, lands on the highest visible window title bar (or the taskbar / screen floor) under her feet, sits with her legs hanging, follows that window when it moves, and falls again when it is minimised, closed or covered.
- **Auto dance to music** (`kira/music_dance.py`, `viewer.html` `kiraMusic`): a Windows loopback listener (PyAudioWPatch, nothing recorded) detects loud + rhythmic audio, estimates BPM and beats; she stands up on her perch and dances in time (one beat = one phase turn), amplitude follows loudness, a harder bounce on each beat, five styles rotating every 14-22 s, and sits again after the song.
- Three switches in the Character tab: `companion_perch`, `companion_hang`, `auto_dance` (all default on). Settings are read live.
- Tests: `test_perch.py`, `test_music_dance.py`, `test_pet_controller.py`.
- Not verified on a real Windows desktop (sandbox): sit/hip height fractions in `perch.py` (`FEET_FRACTION`, `SIT_HIP_FRACTION`), multi-monitor with different DPI, and the look of the new dance poses need a visual pass.

## 2026-11-20 (Gemini Live primary voice + local fallback)

- Added a dedicated Gemini Live audio worker using the official Google Gen AI SDK. Microphone PCM is streamed directly to the Live session and returned PCM audio is played directly to the selected output device; the primary path does not use local STT or Piper.
- Connected the existing Google provider credentials from Connections without storing a second API key. Added Gemini Live model selection and made Gemini Live the default voice engine.
- Added automatic fallback after a Gemini Live connection/session failure: the existing local Qwen3-ASR/Whisper → chat model → Piper listener starts after the Live audio streams are released.
- The home microphone button now starts/stops the configured primary engine (Gemini Live by default); the Voice-page control remains synchronized. Added a selectable local-only primary mode and clear status reporting for connection, active Gemini Live and local fallback.
- Added unit coverage for Google credential selection, device fallback and migration from the legacy local-only setting. Added `docs/GEMINI_LIVE_FA.md` for setup and operation.
- Requires the `google-genai` SDK. Automated tests were not run in this environment; hardware-level duplex audio, interruption behaviour and failover still need Windows smoke testing.


## 2026-11-20 (voice UX and playback diagnostics; Gemini transport superseded below)

- The local-only listening mode was explicitly labelled as STT so it could not be mistaken for a Gemini Live conversation. The later Gemini Live implementation below supersedes that intermediate UI state.
- Added a persistent status badge to the main chat header; it is now updated with the actual Gemini Live or local fallback state.
- Improved Windows Qt playback diagnostics: QMediaPlayer backend errors now include the backend error code, media status and actual error string; invalid media is reported immediately instead of waiting for the playback timeout.
- Windows local Piper playback still requires a real-device smoke test; the diagnostic changes do not claim that silent playback is fixed without that evidence.


## 2026-11-20 (voice playback, local live conversation, Initiative)

- Fixed the Session presentation capability matrix: the Session controller can now access the already-declared `_save_warned` state used by proactive Initiative persistence, preventing the optional check-in from failing with `AttributeError`.
- Added an explicit **Start/Stop live conversation** control to the Voice page. It starts the existing local microphone -> Qwen3-ASR/Whisper -> chat -> Piper speech loop, enables spoken replies, disables wake-word sleep while live mode is active, and synchronizes its state with the chat microphone control and listener failures.
- Removed the misleading selectable Gemini Realtime runtime option. Its provider/model fields are visibly disabled until the actual Google Live transport is implemented; the working local live mode remains available now.
- Unified WAV and compressed-file playback through Qt `QMediaPlayer` / `QAudioOutput`. Piper WAV output no longer uses the separate `QSoundEffect` backend, and output volume is clamped to the supported 0..1 range. Playback start failures continue to surface through the existing timeout/error reporting.
- Re-apply Qwen3-ASR generation-config cleanup immediately before every transcription to handle Transformers wrappers that mutate generation settings between utterances.
- Verification: source changes committed on a dedicated branch. Windows audio-device playback, microphone capture and full application smoke tests still require execution on the target Windows machine; no claim of hardware playback verification is made.

## 2026-11-20 (shortcuts, Appearance, proactive messages)

- Shortcuts (`ui/shortcuts.py`): Ctrl+L focus the message box, Esc stop the answer, Ctrl+1..7 switch tab, Ctrl+, open Connections & Models. Delete on the focused list: models table = move to «منسوخ» (reversible), API table = delete API (asks), Route list = delete Route (asks), chat view = clear this character's history (asks).
- Fixed Appearance: brightness and background colour only changed the (mostly transparent) window background, never the chat/avatar cards or group boxes. `theme.appearance_tint` now feeds both `character_style` and `build_style`.
- Proactive messages: they could practically never fire (window had to be the active one, on the chat tab, input unfocused, and a due memory had to exist). Gates relaxed (window need not be active; taskbar flashes), and when nothing is worth recalling a short friendly nudge (`build_casual_message`) is sent under the same idle/cooldown/2-per-day/quiet-hour limits. Opt-in per character is unchanged; `initiative_casual` (default on) turns the nudge off.

## 2026-11-20 (Jakob's law pass + chat action fixes)

- Fixed: copy / edit / speak chips were missing on every freshly streamed reply (only history-restored messages had them) - the final streamed render now carries the footer, for every character.
- Fixed: chips were only clickable on the tiny glyph; the whole chip is now the link. Chips are smaller.
- Buttons are smaller app-wide (1 px border, 3x11 px padding, weight 600).
- Settings check boxes are now on/off switches (`components/switch_checkbox.py`, a QCheckBox subclass: same API). Lists of choices (model picker, skills) stay check boxes.
- Persian labels for Ollama Edit/Cancel and the Skills tab; the Characters sub-tab no longer shares its name with the top tab ("فهرست شخصیت‌ها").

## 2026-11-20 (AI tab redesign: "API" box + tabbed "مدل‌ها" box)

- New "API" box (`components/api_panel.py`): key entry, then the registered APIs with per-row refresh and delete (double-click edits the key). Replaces the old add panel, "Registered APIs" and "API Details" boxes.
- New "مدل‌ها" box (`components/models_panel.py`) with tabs فعال / رایگان / غیررایگان-نامشخص / منسوخ-غیرفعال (counts in titles), search, full model names (never elided), toggle switch, price pill (price unknown is never shown as free), status dot with last-test tooltip, a per-model "تست" button (one tiny real request via `HybridRouter.test_route`, on a throw-away settings copy) and "منسوخ"/"بازگردانی" buttons.
- `kira/model_catalog.py` (Qt-free): tab rules, archive/restore (`settings["model_archive"]`), saved test results (`settings["model_tests"]`). Archiving switches the Route off, never deletes it; restored models come back OFF.
- Removed: "test all models", select-all/select-free check boxes, the free-only filter combo (the free tab replaces it), `cloud_model_*` view fields. The old Route editor stays in the collapsed advanced section.
- Tests: `test_model_catalog.py`, `test_api_models_panels.py`; GUI tests updated (`api_panel`, `models_panel`).

## 2026-11-20 (Route hygiene: auto model sync, dead/non-free routes, slimmer Route editor)

- Fixed: the model-catalog refresh passed discovery's list of dicts to `reconcile_provider_models`, so valid routes looked stale and were retargeted to another model. New `routes.catalog_entries/catalog_ids/catalog_free` accept every discovery shape.
- Model catalogs refresh automatically 15 s after start when `model_catalog_refreshed_at` is older than 12 h.
- Refresh switches off (never deletes) routes whose model is explicitly no longer free (`route_free_only`, default on), removes routes whose model is gone, and retargets to the provider's recommended model when every route of a provider is dead.
- The router switches a route off after 2 consecutive "model not available" answers (`routes.AUTO_DISABLE_AFTER`) and records the reason in `route_notes`; the last enabled route is never switched off.
- Fixed: the Route "connection test" cut Gemini off at the route's 18 s default while real chat used 60 s. `routes.effective_timeout` is now the single rule for both (Google routes left at the default get the cloud maximum; explicit values are kept).
- 429 errors now explain themselves from the provider's body (`hybrid_ai.quota_kind`): `limit: 0` = no free quota (the route is switched off at once), per-day quota used up, or an ordinary rate limit. The generic "try again in a few minutes" hint is no longer appended when the cause is known.
- 404 errors now show the replacement model the provider names (e.g. `gemini-2.5-flash` -> `gemini-3.8-flash`).
- Route editor: removed up/down/default buttons (drag and drop remains), merged the two Benchmark buttons into one menu, removed the redundant "deselect all" button.
- Tests: `test_route_hygiene.py`, `test_route_editor_widget.py`, `test_model_replacement_hint.py`, `tests/window_factory.py` (GUI tests build a fully composed window like bootstrap).

## 2026-11-15 (desktop attachment, project path and neon icon fixes)

- Added a non-destructive Ollama model-storage setup script that copies existing model blobs to the shared A: data folder and sets the user-level `OLLAMA_MODELS` location.
- Chat attachments now accept files up to 50 MB and ZIP archives. ZIP files are read in place without extraction, with limits on archive size, entry count, per-file size and total uncompressed size; only bounded text content is sent to the model.
- The file picker now lists ZIP archives. Attachment loading can be cancelled from its tile, including while a file is still being read.
- Kira directly reports the currently selected Ai1 Code project folder when asked where it is.
- Toolbar vector icons use the active character's neon accent palette instead of the old grey defaults.
- Added regression coverage for ZIP parsing, large files, cancellation and project-folder questions.

## Version

- Current version: `1.1` (single source: `VERSION` in `kira/config.py`).
- Build metadata: `kira/build_info.py`, stamped automatically by `scripts/build_metadata.py`; the developer is detected from the build environment (Codex / OpenCode / Claude Code / ChatGPT), never typed by hand. Rule: `docs/VERSION_METADATA_FA.md`.

## 2026-11-13 (mandatory version metadata and developer attribution)

- The Settings → General page now has an About section showing Version, Build date (Gregorian `YYYY-MM-DD`), Build time (`HH:MM`, 24-hour) and Developer. The build stamp is generated, not hand-edited.
- New `kira/build_rules.py`, `kira/about.py`, `kira/build_info.py` and `scripts/build_metadata.py`: the developer tool is auto-detected (explicit `KIRA_DEVELOPER` override → build-host markers → recorded stamp → git author) and must be one of the four approved tools.
- Release gate: the workflow runs `python scripts/build_metadata.py --check`, and `scripts/build_release.py` re-stamps then validates version, date, time, developer and the CHANGELOG entry, so an incomplete metadata set stops the release.
- Tests: `tests/test_build_metadata.py` (portable) plus an About assertion in the Windows GUI suite.

## 2026-11-13 (no `</>` button: Kira understands coding requests by herself)

- The `</>` button and the on/off mode are gone. Kira's tab decides from the wording (text or voice) whether the person wants a coding mission, a question about the project, or ordinary talk (`chat_code.classify_intent`, project vocabulary, and a one-word model check for ambiguous messages; any doubt = normal chat). The project folder is asked once, the first time it is needed; "change the project folder" works in words. `/off` was removed; the other slash commands stay as optional shortcuts.
- Better programming: Kira's specialty prompt rewritten (root causes, edge cases, runnable code, honesty); the agent now gets the conversation so far and a project brief, follows explicit engineering rules, sees syntax / JSON errors right after each edit, and cannot finish after edits without a passing check (one nudge).
- Chat rendering: ``` fenced code and `inline code` are now drawn as code in every reply (also while streaming) via `chat_render.rich_body_html`.
- Tests: intent / classifier / vocabulary tests, 6 agent-quality tests, GUI tests for no-button, folder asked once, classifier routes (30 GUI tests total).

## 2026-11-12 (Ai1 Code became an autonomous agent)

- New `kira/auto_agent.py`: Agent loop (INSPECT -> PLAN -> EDIT -> TEST -> FIX -> RETEST -> PACKAGE) + tools (`plan list read search write replace delete run shell finish`) + runner (Popen, timeouts, Stop kills processes, env stripped of secrets, test logs in the chat) + zip builder (`<Project>_YYYY-MM-DD_HH-MM_IRST.zip`, `testzip` check, `AI1CODE_REPORT.md`). The agent edits a copy; the original is the restore point, and external edits to it while the agent runs are reported.
- In code mode no `@file` or command is needed: task wording starts a mission (one start confirmation), other messages start a read-only investigation that finds the relevant files itself. `shell` commands and folder deletes ask for approval every time. `/auto`, `/patch`, `/run` remain as explicit overrides; `/patch @file` is the previous one-file Diff flow.
- Chat: the agent's plan, steps and test output stream into the chat; the final bubble lists changed files, runs, warnings and a "open the zip folder" link (`kira-code://open/<id>`).
- Tests: `tests/test_auto_agent.py` (14, portable, in CI) and 5 new agent cases in `tests/test_chat_code_gui.py` (26 total). Not verified here: real Windows 11 PowerShell, real model quality (tests use a scripted model), long missions with the Route Manager routes.

## 2026-11-12 (Ai1 Code moved into Kira's chat)

- Ai1 Code is no longer a menu item / separate window. A `</>` button in Kira's composer (only on her tab) switches her chat into code mode for a chosen project folder. `kira/code_workspace.py` was removed; new `kira/chat_code.py` (Qt-free logic) and `kira/chat_code_ui.py` (`CodeChat`).
- Ask about code with `@file` mentions (up to 3 files); edit requests come back as a coloured Diff inside the chat with ✅ apply / ❌ reject links (also `/apply`, `/reject`). Apply asks once more, refuses stale files, keeps one `.ai1code.bak` and writes atomically. Commands: `/files`, `/project`, `/run` (PowerShell, per-command confirmation, 120 s timeout), `/off`, `/help`.
- Safety: files too large for the context budget, non-UTF-8 files and files containing secrets are analysis-only (a truncated context would otherwise delete the tail of the file); secret files / runtime folders stay invisible; CRLF and the final line break of the original file are preserved in proposals.
- Chat view: links are now handled by `MainWindow.on_chat_link` (http / https / mailto open in the browser, `kira-code://` runs approve / reject, anything else is ignored). Code answers render ``` blocks and `inline code` and are never spoken.
- Tests: `tests/test_chat_code.py` (portable, added to CI) and `tests/test_chat_code_gui.py` (Qt offscreen, 21 cases). `tests/test_gui_offscreen.py` now asserts the menu has no Ai1 Code entry.
- Not verified here: the real Windows 11 desktop (PowerShell `/run`, dialogs), and `tests.test_gui_offscreen.test_15_...` fails in this sandbox before and after this change (it also fails on the unmodified ZIP).

## 2026-11-12 (3D body: human-like turning, dancing)

- Turning (`turn_back` / `turn_left` / `turn_right` / `face_front`, also back to front on `reset`) is no longer a rigid, linear spin: the yaw is eased and speed-limited (~1.5 s for 180 degrees), the head leads, the chest lags, the feet take alternating steps, the hips dip a little and the arms swing against the legs.
- NEW poses `dance` (lively: arms up and pumping, hips and chest swaying, knees bouncing) and `dance_sway` (slow, gentle). Phrases: «برقص», «آروم برقص», "dance"; stop with «بس کن», «دیگه نرقص», «وایسا», `stand_up` or `reset`; a dance also ends by itself after 40 s. Any arm / torso / leg / head pose replaces a running dance.
- Not seen on the real model (no WebGL in the sandbox): tuned numbers live in the `POSE` table and the turn block of `applyBody` in `assets/vrm/viewer.html`.

## 2026-11-12 (chat controls Kira's 3D body: raise hand, turn back, bend, sit ...)

- NEW `kira/body.py` (pure Python): two ways to move the VRM body from the chat. (1) The user's own message is read at once (`parse_user_command`, Persian + a little English: "دستتو بیار بالا", "پشتتو کن", "خم شو", "بشین", "تعظیم کن", "دست تکون بده", ...). Ordinary chat, first-person statements ("دستمو بردم بالا") and negations ("بالا نبر") do nothing. (2) The model can write `[body:raise_right_hand]` / `[body:turn_back+bow]` after its emotion tag; the tags are removed from text, speech and history (`ReplyMeta.body`).
- The system prompt tells the model it has a body and the pose names while Kira's VRM is on screen, and which movements the app already performed for this message (no repeats, no "I can't").
- `assets/vrm/viewer.html`: `window.kiraBody([...])` + 26 held poses (raise right/left hand, arms up/out/forward, wave, hands on hips, bow, bend forward/back, lean, turn back/left/right, head up/down/left/right/tilt, sit, crouch, leg lifts) blended smoothly on top of idle + gestures; releases: `reset`, `lower_hands`, `stand_up`, `face_front`, `head_front`; existing gestures (nod, shake, hop, spin, tilt, wave) also reachable. A held pose lets go by itself after 150 s (`HOLD_S`); bow and waves after a few seconds.
- Left/right = the character's own sides. Only Kira's VRM body moves (Ren / Mika use the PNG art and get no body prompt). Setting `body_control` (default true) turns it off.
- Tests: `tests/test_body.py` (phrases, tags, parser, page table in step with Python). The pose angles could NOT be viewed here (no WebGL in the sandbox); only the pose engine was run against mock bones. Fine-tune angles in the `POSE` table of `viewer.html`.

## 2026-11-12 (fix: relay `event` error, Game Mode self-detection)

- BUG fixed: `SessionRelay` had a slot called `event`, which overrode `QObject.event(QEvent)`. Every Qt event delivered to the relay (timers, child/deferred-delete events) ran `on_stream_event` with a QEvent -> endless `AttributeError: 'QEvent' object has no attribute 'get'` in the console. Slot renamed to `stream_event` (connection updated). This was an old latent bug, not caused by the VRM avatar.
- Game Mode no longer suggests itself for Kira: foreground windows whose process is Kira's own tree (parent/children via psutil when installed), runs from the project folder, is a console / terminal / python launcher / `QtWebEngineProcess.exe`, or has `Kira` / `Ai1` as a word in its title are never treated as games.

## 2026-11-12 (VRM: animation bug fixes, breathing, bust physics)

- BUG fixed: legs, feet, hands and toes were never reset between frames, so a gesture (leg/foot/hand reactions) added its rotation again on every frame: legs spun upright, the pose fell apart and never returned to idle. Every humanoid bone now starts each frame from the rest pose; gestures only add on top, so the idle pose always comes back.
- Breathing is now visible: chest/upper-chest rotation, shoulder lift, small hip bob and weight shift, plus chest expansion on the in-breath (raw chest bone scaled, head and arms counter-scaled).
- Bust physics: the model's `Bust` spring bones were too stiff for idle motion; they are loosened at load (stiffness 0.75 -> 0.25, drag 0.18) and are excited by breathing, weight shift and a chest bounce while Kira talks.
- Not verified here (no Windows / WebGL in the sandbox).

## 2026-11-12 (VRM: moods, framing, click reactions)

- VRM expressions follow Kira's mood more strongly: emotion weights x1.5 on the VRM presets, bigger head tilt per emotion; works for replies, the mood system (`apply_mood_to_avatar`), the mood preview and click reactions.
- Framing: the camera now fits the whole body (hair top to soles of the feet incl. toes) in both the chat card and the floating companion.
- Click reactions: every area in `reactions.json` has 3 variants (expression, voice lines fa/en, body gesture); one is picked at random and never repeated twice in a row. New `FaceAnimator.gesture` signal drives VRM body motions (flinch, shake, nod, tilt, hop, spin, wave, hand_wave, step, stomp, lean, arm flaps).
- VRM click picking is 3D: the page finds the nearest body part (face, hair, torso, clothes, arms, hands, legs, feet) instead of guessing from the click height.
- Not verified here (no Windows / WebGL in the sandbox).

## 2026-11-12 (VRM avatar)

### Kira is now a 3D VRM avatar (assets/vrm/kira.vrm)
- New `kira/vrm_avatar.py` (`KiraAvatar`, drop-in for `AvatarView`) shows the VRM in the chat card and the floating companion while Kira is the active character; Ren / Mika keep their pictures. Rendering: three.js + @pixiv/three-vrm in Qt WebEngine (`assets/vrm/viewer.html`), served from 127.0.0.1 only.
- Idle pose (not T-pose): arms lowered, relaxed fingers, breathing, sway, blinking, eyes follow the cursor, spring bones (hair/clothes) via three-vrm.
- Lip-sync: the existing voice loudness (`Speaker.level` -> `animator.mouth`) drives the VRM mouth shapes aa/oh/ou/ih/ee.
- Emotions: the existing EmotionDirector members (24 emotions) are mapped to VRM happy/angry/sad/relaxed/surprised + a small head tilt; sleeping closes the eyes and lowers the head.
- The three JS libraries (`kira/vrm_vendor.py`) are downloaded to `assets/vrm/vendor/` by install_deps.py or on first start. Without them, without WebEngine/WebGL, or with `KIRA_VRM=0`, the old PNG avatar stays.
- `face.py` gained `kira_art_active`; `backend_png.py` keeps `last_frame`. Model credit and license limits: `assets/vrm/CREDITS.txt` (credit required, no redistribution).
- Not verified here: no PySide6, WebGL or network in the build sandbox - needs a manual run on Windows.

## 2026-11-11 (pink neon glass theme)

### Global UI theme: transparent glass, pink + cyan neon, prominent buttons
- `kira/theme.py` STYLE rewritten: translucent flat surfaces (no gradients), neon pink/cyan edges, violet replaced by pink.
- Buttons are now prominent: stronger fill and a 2px neon border; send button is solid pink.
- Character chat tabs and per-character themes (`CHARACTER_THEMES`, `character_style`) are untouched.
- Not verified here: visual result on Windows (PySide6 unavailable in the sandbox).

## 2026-11-11 (character chat tabs)

### Per-character chat tabs, transparent standing pictures, character-themed glass/neon chat
- Ren's and Mika's pictures now have their backgrounds removed (`ren_full.png`, `mika_full.png`; originals kept). Mika's source picture is three-quarter, not a full standing figure.
- Chat page: a tab strip with one tab per character; each tab is an independent conversation (own history, router, stream) and several characters can answer at once. Tabs show ⏳ while answering and ● for an unread reply.
- Chat history is stored per character (`messages.character_id`, automatic migration; old rows = Kira). "Clear chat memory" clears only the visible character's chat.
- Switching a tab restyles the chat (glass + neon in the character's colours, tinted assistant bubbles) and changes the avatar.
- Mika's specialty prompt updated: history is no longer shared. New `kira/chat_sessions.py`, `tests/test_character_chats.py`; updated `tests/test_characters.py`, `tests/test_avatar_art.py`.
- Not verified here: the tab UI itself (PySide6 unavailable in the build sandbox) - needs the Windows CI / a manual run.

## 2026-11-11

### Ren and Mika artwork; chat page follows the active character
- Added Ren and Mika portraits (Character tab) and full-body pictures (chat page and floating companion).
- Switching the active character now switches the animated character on the chat page and in the floating companion; Kira keeps her own animated PNG with face overlays, Ren and Mika move with the same soft-body rig at reduced strength. Characters without a picture keep Kira's art.
- The Character-tab portrait is cropped to fit instead of stretched; Kira's SVG portrait is unchanged.
- New `kira/avatar_art.py` (pure geometry) with `tests/test_avatar_art.py`; updated `tests/test_characters.py`; added an offscreen GUI test for switching characters.
- Known limit: no blinking or lip-sync for Ren and Mika yet.

## 2026-11-11

### Game Mode Windows CI gate
- Added a Windows runner for Game Mode identity and monitor regression tests using PySide6 with Qt offscreen.
- Made the release packaging job depend on the Windows Game Mode test job, so a failed Windows regression blocks publishing the ZIP.
- Kept the Linux portable test suite and syntax check unchanged.
- Clarified that CI uses mocked foreground-window data and does not replace a real interactive Windows 11 smoke test.

## 2026-11-11

### Temporary portrait removal for release build
- Removed Ren and Mika portrait assets and cleared their built-in image references until replacement portraits are ready.
- Updated the character card to support an intentionally empty portrait without substituting another character's artwork.
- Kept Kira's original SVG portrait unchanged.

## 2026-11-11

### Game detector self-identification fix
- Exclude Ai1's own process ID before game title hints and large-window heuristics.
- Add a regression test using the `Project Kira 1 stable` window title and a full-screen window rectangle.

## 2026-11-11

### Linux regression and Windows ZIP fixes
- Updated the requirements regression test to recognize the intentionally optional `psutil` dependency.
- Added `.gitattributes` enforcement and release-time normalization so every packaged `.bat` file uses CRLF, including archives built on Linux.
- Updated stream/persistence test fixtures to account for LeakGuard's deliberate short-preamble buffering without weakening its filtering behavior.
- Updated GUI navigation tests for the current menu, including the separator and Ai1 Code entry.
- Expanded CI coverage to include streaming, chat persistence and release regression modules.

### Character specialties and profile portraits
- Defined Kira as the coding/software-development specialist, Mika as the medical-information guide, and Ren as the news and intelligence analyst.
- Added scope-aware specialty prompts while keeping model routes, tools and permissions shared across characters.
- Added medical safety boundaries: no definitive diagnosis or independent prescribing, emergency red flags, reputable evidence and privacy-aware handling of sensitive health details.
- Restored Kira's original SVG portrait as her active profile image. Removed the unfinished Ren and Mika portrait assets; their profile image fields are empty until replacement portraits are supplied.
- Added regression coverage for each built-in character's specialty prompt.

### Ai1 Code workspace (initial foundation)
- Added a separate Ai1 Code workspace with project folder selection, file tree, bounded UTF-8 editor and explicit save with a one-time backup.
- Added a PowerShell terminal that requires confirmation for every command; it runs as the current Windows user and is not a sandbox.
- Added a read-only Code Agent that uses shared configured routes without inheriting Kira/Ren/Mika persona prompts or ToolAgent/MCP permissions.
- Project context is bounded and excludes secret/configuration files, runtime/build/dependency directories and symlinks/path escapes.
- Automatic edits, approved Diff application, debugger, breakpoints, Git controls and test orchestration are deferred to the debugging phase.

### Dual Game Mode profiles and permission boundaries
- Added manual Story Mode for offline/story games and Competitive Safe for online/PvP or unknown games.
- Competitive Safe disables game-window Vision/capture, game/system WASAPI loopback and local desktop/app/file/MCP/agent control tools. It retains ordinary chat, web tools and independent microphone/wake-word interaction.
- Added a central ToolRegistry execution guard so restrictions also apply to direct tool calls, confirmations and Agent tasks.
- Unknown profiles fail closed to Competitive Safe; detection only recommends and never auto-enables a profile.
- Story Mode retains existing user-requested desktop controls for offline play; Competitive Safe blocks desktop controls and gameplay input. Both profiles keep code injection, game memory access, graphics hooks, overlays, game-file modification and driver installation disabled.
- Added pure-Python regression tests for profile capabilities and tool-category restrictions.

### Game Mode audio and wake update
- Added Windows WASAPI loopback capture via PyAudioWPatch for default system/game output.
- Game speech is segmented and transcribed locally with faster-whisper; audio is neither saved nor sent to cloud STT.
- Ordinary game dialogue stays silent. A conservative keyword filter with cooldowns allows selected critical, mission and combat alerts.
- Game Mode temporarily enables microphone wake-word listening. Kira stays quiet until called; previous mic/wake states are restored when Game Mode is disabled.
- Loopback capture stops on Game Mode shutdown and application exit.

### Game Mode Vision update
- Capture the active game window once per second only while Game Mode is manually enabled.
- Downscale frames to a maximum 854×480 while preserving aspect ratio.
- Keep only the newest frame in memory; attach it as JPEG (quality 68) when the user sends a message. No continuous upload.
- Stop the capture timer and clear the cached frame immediately when Game Mode is disabled.
- Suppress game-mode suggestions if Game Mode is already enabled.

### Added
- MiniMax Global as a TTS-only Cloud Voice provider.
- Manual Game Mode toggle in the chat toolbar.
- Foreground game detection with one advisory suggestion per process launch.
- Guarded game-window screenshot capture, attached to the next user message only while Game Mode is manually enabled.
- Regression tests for Game Mode's default-off and capture-safety behavior.
- Product naming clarification: Ai1 is the application; Kira, Ren and Mika are characters.

### Preserved
- Existing Google AI Studio, Groq and ElevenLabs providers.
- Existing local Edge TTS and Windows speech fallbacks.
- Existing independent STT configuration and chat Route Manager.
- Game Mode remains off at startup and never auto-enables after a game is detected.


### Ai1 Code phase 2: Diff and explicit patch approval
- Added selected-file replacement proposals through the independent Code Agent.
- Added strict response-marker validation and rejection of malformed or empty proposals.
- Added read-only unified Diff preview and explicit user approval before writing.
- Added stale-file/editor checks, one-time backup and atomic replacement for approved changes.
- Blocked patch proposals for contexts containing redacted credentials to avoid overwriting real secrets with placeholders.
- Added regression tests for patch-response validation. Windows GUI and PowerShell behavior still require manual testing on Windows 11.


## 2026-11-11

### Native Function Calling
- Added native JSON-schema tool calls for OpenAI-compatible Route providers.
- Reused the central ToolRegistry schemas and execution pipeline; native calls do not bypass permissions, confirmations, duplicate-call protection or Game Mode restrictions.
- Preserved standard assistant tool-call and tool-result messages across native rounds, with a safe text-result bridge if a later route lacks native support.
- Kept text-protocol fallback for providers without a native adapter.
- Added provider parsing and native message-normalization regression tests.

### Game Mode detector hardening
- Added an explicit product-window-title exclusion for Project Kira 1 stable / Kira / Ai1 windows in addition to the current-process-ID guard.
- Added regression tests for a mismatched reported PID and a positive large-game-window detection to avoid suppressing real games.

### Portable Game Mode identity regression coverage
- Extracted the current-process and known Ai1/Kira window-title exclusion into a pure-Python helper and added CI coverage for the false-positive case and a real-game negative control.

### Windows Game Mode test fixture correction
- Initialize a Qt application in the Game Mode test fixture so the primary-screen geometry query is available on Windows CI's offscreen platform.
- Include both Game Mode test modules in workflow path filters so future edits trigger the release gate.


### Native Function Calling: Gemini and Ollama
- Confirmed Google AI Studio/Gemini native tools through the existing OpenAI-compatible adapter and added a regression test for the official Google endpoint.
- Added Ollama `/api/chat` native tool requests, response parsing and assistant/tool-result message preservation.
- Added safe capability fallback: Ollama models that explicitly reject tool calling are marked unsupported so the router can continue to another native route or use the text protocol.
- Kept ToolRegistry validation, permission checks, confirmation flow, duplicate-call protection and Game Mode execution guard unchanged.

### Native Function Calling test fixture correction
- Build the assistant tool-call argument string with `json.dumps` in the Ollama multi-round regression fixture to avoid invalid Python escaping.


### Model Discovery and Route Manager validation
- Added Gemini pagination regression coverage for the official model-list API, including filtering non-chat models and verifying the API key remains in the header.
- Strengthened Google provider registration coverage to verify all discovered models remain visible while only the selected default model is activated as a Route.
- Extended Route Manager source-level tests to cover asynchronous refresh, registry merge and model enable/disable wiring.


### User-memory migration and backup hardening
- Include `kira_persona_memory.json` and `kira_evidence.sqlite3` in legacy-data detection and per-file migration.
- Include persona memory in rolling backups; keep evidence memory backed up through SQLite's online-backup API.
- Add tests proving the external Windows data directory/override, non-destructive migration, and backup restoration data coverage.

- Explicitly grant the release workflow `contents: write` so the GitHub Release action has the permission required to publish ZIP assets.

- Include the release workflow YAML in its own path filter and test that persona/evidence-only legacy folders are recognized as user data.

- Remove the duplicate top-level workflow permissions key; retain one explicit `contents: write` permission for release publishing.


### Character-specific long-term memory
- Isolate voice samples, facts, moments, habits and conversation summaries by active character.
- Preserve Kira's existing memory filename; create separate Ren/Mika files under the external data directory.
- Keep the evidence-backed fact index Kira-only and prevent Ren/Mika prompts from retrieving Kira's indexed facts.
- Bind the Memory dialog and memory maintenance to the active character. Short-term chat history remains shared.
- Add tests for profile isolation, Kira compatibility, evidence-index isolation and per-character voice/joke state.

- Extend migration and rolling backups to all per-character memory files; add Ren/Mika preservation and destination-wins regression tests.
- Make memory prompt headings and Memory dialog wording follow the active character rather than hardcoding Kira.
- Add context-scope restoration coverage for nested character memory calls.

- Prevent Ren/Mika long-term memory from digesting or summarizing shared legacy chat rows that lack a character ID.
- Clear shared-chat voice/digest samples for all profiles when the shared chat is cleared, while preserving each profile's facts, moments and habits; only Kira resets the currently shared mood state.
- Document the legacy evidence-index limitation: historical facts cannot be attributed to a character because older chat rows lack character IDs.
# 2026-11-13 — Kira coding-agent upgrades
- Added static AST project maps for Python modules, imports, classes and functions.
- Added automatic Ruff lint after Python edits, with Pyflakes fallback, while retaining immediate syntax / JSON checks.
- Added snapshot-based diff and Git-style status/diff tools without enabling repository writes.
- Added an independent diff-review pass; changed tasks cannot finish until checks and a clean review complete.
- Added `.ai1/PROJECT_MEMORY.md` for durable verified conventions, test commands and pitfalls carried with delivered project ZIPs.
- Planner, executor and reviewer requests now use the existing `deep`, `surface` and `reflection` role routes and fallback behavior.
- Prompt now directs Kira to create focused tests for changed behavior where the project supports them.

