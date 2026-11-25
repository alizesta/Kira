# Interface Language Settings

## Contract

The desktop interface defaults to **English** for new installations and for settings files that do not contain a language preference. Persian remains selectable from the Preferences page.

The persisted configuration key is:

- `ui_lang = "en"` — English, left-to-right.
- `ui_lang = "fa"` — Persian, right-to-left.

The interface-language preference is independent of speech recognition, speech synthesis, model routing, and the language used in an individual conversation.

## User workflow

1. Open the General/Preferences settings page.
2. Find the **Interface language** selector.
3. Select **English** or **فارسی**.
4. Save the settings.
5. The session controller retranslates registered UI strings and sets the Qt layout direction: left-to-right for English and right-to-left for Persian.

## Persistence and migration behavior

The setting is stored with the rest of the application configuration in the user's settings file.

- A new settings file receives the English default.
- A legacy settings file with no `ui_lang` key receives the English default through the normal defaults merge.
- A settings file that explicitly stores `"fa"` keeps Persian after an application update.
- An unsupported or missing value falls back to the English translation catalog in the UI translation lookup.

No user setting is rewritten from Persian to English merely because the application default changed.

## Implementation map

| Component | Responsibility |
|---|---|
| `kira/config.py` | Defines the default `ui_lang` value as `en`. |
| `kira/strings.py` | Holds the English and Persian UI string catalogs. |
| `kira/ui/pages/preferences_page.py` | Presents the language selector and reads the persisted value. |
| `kira/ui/main_window_session.py` | Looks up translated strings, retranslates pages, and switches Qt layout direction. |
| `kira/ui/main_window.py` | Uses the English fallback for character-specific input hints during startup. |
| `tests/test_config.py` | Verifies the English default and preservation of an explicit Persian preference. |

The English and Persian catalogs currently contain matching key sets. When adding or changing a UI string, update both catalogs with the same key and equivalent meaning.

## Change policy

- Keep the persisted values `en` and `fa` stable; do not store translated labels as configuration values.
- Never infer the user's speech-recognition language from the interface language.
- Preserve explicitly saved user preferences during migrations.
- Add regression coverage when changing the default or the settings migration path.
- Verify RTL and LTR rendering on Windows; source-level tests alone cannot verify visual layout.
