# Dashboard UI hand-off (Claude 1 -> Claude 2)

Reference: the "Kira's Neon Companion Dashboard" image. Goal: the main chat page looks exactly like it. The user will hand over
Kira's picture when the work is finished (see "Portrait pictures"). Test and bug-fix pass comes at the very end; nothing below
has been run yet (the repository is private to Claude 1's tools, so only code was written).

## Files

| File | What it owns |
|---|---|
| `kira/ui/chat_shell.py` | The three columns. Left: brand, navigation, profile card, Quick People (the character tabs, vertical), conversations. Centre: greeting, three stat cards, chat card. Right: Call/Voice/Surprise row, playlist card, quote card (appended to the avatar card). |
| `kira/ui/dashboard_chat.py` | Message bubbles (avatar + time + double tick), the "Today" chip, header icons, composer pill, portrait card. |
| `kira/ui/appearance_runtime.py` | Calls `apply_chat_shell` then `apply_dashboard_chat` at the end of `apply_appearance` (each is idempotent, once per chat page). |
| `tests/test_chat_shell.py`, `tests/test_dashboard_chat.py` | Offscreen Qt tests for both modules. |

## How the skin works (read before changing it)

* Existing widgets are **moved**, never recreated. `build_chat_tab()` is untouched.
* `SessionController.apply_chat_theme()` replaces the page stylesheet on every character switch, `refresh_conversation_list()` rebuilds
  the rows, `refresh_tab_buttons()` resets button text, `add_chat()` / `message_html` build the bubbles. The skin **wraps these on the
  controller instance** (class untouched) so it survives them. Do not call the class methods directly.
* `resizeEvent()` of the session controller still sets the avatar card width (200-300) and hides it below 640 px.
* `main_window_session.message_html` is replaced at runtime by the bubble renderer (system/error messages keep the old look). Messages
  painted from history carry no time, because their real time is unknown (`_suppress_conversation_refresh` is set while history is painted).

## Real vs display-only

Real: Chat/Settings navigation, Quick People (switches character), conversations, Kira's Mood card (mood service), greeting by time of
day, composer (send, attach, stop), every old toolbar control (moved into the tray that the ✦ button opens).
Display-only ("Coming soon" in the status line): Home, Voice Call, Memories, Gallery, Journal, the three header round icons, Our Bond
(Level 12, 72 %), Today's Vibe, Call/Voice/Surprise, playlist, quote, profile heart, the 🔍 and ⚙ icons in the chat header, the emoji
button.

## Portrait pictures

Put one picture per character at `assets/dashboard/<character id>_portrait.png` (for example `kira_portrait.png`, `ren_portrait.png`,
`mika_portrait.png`). A character with a picture shows the portrait card (name over the lower edge); one without keeps the animated
avatar. The user will supply Kira's picture; place it there.

## Not done yet (updated 2026-11-27 Claude 2, after rendering the real window offscreen)

* Steps 1-4 of the user's order (rounded bubbles, typing box, news panel hidden, column proportions) were written by Claude 1 in 7c72d69; Claude 2 rendered them (tests/window_factory needs `vision_runtime_provider` + `desktop_context_application_service` stubs) and fixed: nav buttons were 66 px (QSS min-height + padding add up; now fixed 46), duplicate "Today" chip removed (header chip only), bubbles shrink to their text, profile quote wraps, left column fits 1024 px.
* Done (Claude 2, 2nd pass): left column no longer clipped (conversation sidebar ignores its min width, no scrollbar), Quick People rows show picture 48 px + badge (Ren flame, Mika flower, Kira star) + "Online".
* Still different: the extra header button is the real "Show character on desktop" action (kept); the OS-style top bar with the hamburger above the page; Kira's picture (waiting for the user, `assets/dashboard/kira_portrait.png`); bubble corners / typing box not seen in a render yet (no messages in the offscreen window).

* Done (Claude 2, 3rd pass, display only): red dot on the bell, playlist waveform, rain-cloud icon in Today's Vibe, "Kira ✦ / Always here for you" caption above Call/Voice/Surprise.

* Done (Claude 2, 4th pass): Kira's picture `assets/dashboard/kira_portrait.jpg` is the chat portrait (right card, name painted over it) and her round avatar in profile / Quick People / chat bubbles; other characters keep their own avatar (`_sync_portrait`). Hamburger bar is hidden on the chat page only (still shown on other pages); a pinned "Settings" button at the bottom of the left column opens the same `views.nav_menu`. The "Kira's Mood" wave is live (`_Sparkline`, `wave_shape`): anger/excitement = tall waves, worry/shyness = small and dense waves, calm/sad = slow gentle wave; it follows `mood_service.current()` emotion + intensity (no real audio analysis yet; hook a voice-level feed into `set_mood` if wanted).

* Done (Claude 2, 5th pass): Kira's chat background `assets/characters/kira_chat_background.jpg` is wired through `CHARACTERS["kira"]["chat_background"]` (same mechanism as Mika). Note: `test_theme_applies_background_only_when_a_path_is_supplied` already failed before this (appearance_tint gets a non-numeric brightness in the test's appearance dict); not touched.

## Test checklist for the final pass

Run `run_tests.bat`. Likely failures: tests that assert the old layout (avatar width, tab row position, composer button order) or the
old bubble HTML (the replaced `message_html` persists in the process once the skin is applied).
