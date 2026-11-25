# Version Metadata and Developer Attribution (Mandatory Rule)

This document explains the rule recorded in `PROJECT_CONTEXT.md`, section **Version metadata and developer attribution**. It is mandatory for all developers and agents (Codex, OpenCode, Claude Code, and ChatGPT).

## What is displayed and where

A group named **About** appears under **Settings → General** with four rows:

| Row | Value | Format |
|---|---|---|
| Version | `VERSION` from `kira/config.py` | One line, starts with a digit (for example, `1 stable`) |
| Build Date | Gregorian build date | `YYYY-MM-DD` |
| Build Time | 24-hour build time (Asia/Tehran) | `HH:MM` |
| Developer | Automatically detected development tool | Exactly one of four allowed names |

None of these values is typed manually. Version comes from `kira/config.py`; the other three come from the generated `kira/build_info.py`. `kira/about.py` prepares all four rows for the UI. If `build_info.py` is missing, the UI shows `unknown` instead of raising an error.

## Single source of truth for each value

- **Version:** only `VERSION` in `kira/config.py`. No other manually maintained version string is permitted.
- **Build Date / Build Time / Developer:** only `kira/build_info.py`. `scripts/build_metadata.py` regenerates this file for every Build and Release. **Manual editing is prohibited.**
- **Change history:** `CHANGELOG.md`. Every change must keep the version and build attribution metadata aligned with the changelog/release notes.

## Automatic developer detection

`scripts/build_metadata.py` determines the tool name in this priority order; the first valid value wins:

1. Explicit `KIRA_DEVELOPER` environment variable (for example, `KIRA_DEVELOPER=Codex`). Unknown values are errors.
2. Build/Release host markers: `CLAUDECODE` / `CLAUDE_CODE_ENTRYPOINT` → Claude Code; `CODEX_SANDBOX` / `CODEX_HOME` → Codex; `OPENCODE` / `OPENCODE_SESSION_ID` → OpenCode; and `AI_AGENT` / `AGENT` (normalized).
3. Previously recorded value in `kira/build_info.py`.
4. Git author/committer name.
5. If none succeeds, raise an error (`MetadataError`). There is no guessed or default value.

The only accepted names are `Codex`, `OpenCode`, `Claude Code`, and `ChatGPT` (common spelling variants such as `opencode`, `open-code`, `claude`, and `chatgpt` are normalized). Any other name stops the Release.

## Build and Release validation

- **CI:** the **Validate version and build metadata** step runs `python scripts/build_metadata.py --check`. It does not rewrite files; it validates version, date, time, developer, and the current version reference in `CHANGELOG.md`.
- **Release script:** `scripts/build_release.py` calls `ensure_release_metadata()` at the start of `main()`. It first regenerates `kira/build_info.py` using the current Tehran time and detected developer, then runs the same validation. If anything is wrong, it stops with `Release stopped: …` and a non-zero exit code; no ZIP is created.
- Both paths print the full metadata JSON so it can be referenced in Build/Release logs.

## Required steps for every developer

1. For a new Release, update `VERSION` in `kira/config.py`.
2. Add a section at the top of `CHANGELOG.md` containing the exact same `VERSION` string; this is required by validation.
3. Ensure the Build/Release environment has the correct tool marker or `KIRA_DEVELOPER`, so the wrong developer is not recorded.
4. Before Commit/Release, run:

```bash
python scripts/build_metadata.py --check
```

Then, when needed, run once without `--check` to stamp `kira/build_info.py`.

5. Add regression tests for new behavior. The rule's tests are in `tests/test_build_metadata.py`; a UI check is also in `tests/test_chat_code_gui.py`.

## Maintenance note

`scripts/build_stage3_release.py` is a one-off legacy path for rebuilding the Stage 3 archive and is not part of the current Build/Release flow. The metadata gate applies through `scripts/build_release.py` and CI.
