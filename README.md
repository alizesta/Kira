[فارسی](README.fa.md) — [Documentation index](docs/README.md)

# Project Kira

Kira is a Windows 11 desktop companion and AI assistant. The application combines a character-driven chat interface with local and cloud model routing, persistent conversations, voice interaction, file and image input, desktop awareness, and a task-oriented coding agent.

The repository's primary documentation language is **English**. Persian translations are stored alongside their English source with the `_FA` suffix, or with `.fa.md` for the root README.

## Installation and first launch

1. Run **install.bat**. On the first installation, choose the data directory or use the suggested default.
2. The installer prepares Kira's application dependencies and local speech components. Ollama is a separate optional stage: Setup Manager detects an existing server or asks before installing the engine, then confirms the exact model's registry size, free disk space, and hardware fit before downloading.
3. A downloaded model is not automatically selected. Setup Manager asks separately before changing Kira's local chat route. Rerun `python -m kira.setup_manager --interactive` to resume or repair setup; use `python -m kira.setup_manager --status` for read-only diagnostics. See [Local Runtime Setup](docs/LOCAL_RUNTIME_SETUP.md).
4. Start the application with **start_kira.bat**.
5. To configure a cloud model, open the Route settings, choose **Add API**, and enter the provider's API key. Kira validates the key and discovers models through the provider API. See the [API Manager guide](docs/API_MANAGER.md) for the current provider workflow.

The updater is **update_kira.bat**. It updates code and dependencies and runs the configured focused checks.

## AI routing

Kira uses explicit routing boundaries rather than sending every request to whichever provider happens to be available.

- Ordinary conversation and requests that explicitly require an uncensored local path use the configured local Qwen model.
- Deep reasoning, demanding analysis, and complex coding tasks use the designated Google Gemini routes. They do not silently spill over to an unrelated provider when that route is unavailable.
- Image understanding uses the configured Google vision route. The installed local GGUF chat model is text-only.
- Provider priorities, route roles, model allowlists, and failover behavior are managed in Route settings.

Available cloud integrations include Google Gemini, Groq, Mistral, OpenRouter, Cloudflare, and APInex where configured. A provider is not active merely because it is listed: the user must configure and enable it.

## Main capabilities

### Chat, memory, and characters

- Independent conversation history for the available character profiles.
- Persistent chat storage and explicit history-management actions.
- Evidence-oriented memory that can retain a fact together with its source context.
- Character-specific presentation and behavior, while sharing the application's routing and safety boundaries.

### Web search and research

- Quick web search can be invoked from the chat composer.
- Multi-source research can search and read independent pages, compare evidence, and produce a cited report with confidence and evidence limitations.
- Research is separate from ordinary quick search and can be stopped or continued.

See [Web Research](docs/WEB_RESEARCH.md).

### Files, images, and desktop tools

- Attach files through the attachment button, drag and drop, or supported clipboard image input.
- Supported text and document formats can be read; image understanding requires a compatible vision route.
- The Tool System can inspect permitted information about the Windows computer and perform supported actions. Sensitive file operations require explicit confirmation; it is not an unrestricted shell.

See [Tools and computer access](docs/TOOLS.md).

### Voice

Kira supports a Gemini Live conversation path and local speech components. Local speech recognition uses the configured offline ASR engine with its supported fallback; local speech generation uses Piper. The local path does not send microphone audio to cloud speech services. Cloud Live interaction is a separate, explicitly configured mode.

See [Local Voice](docs/LOCAL_VOICE.md), [Voice Routing](docs/VOICE_ROUTE.md), and [Gemini Live](docs/GEMINI_LIVE.md).

### Eye Mode

Eye Mode is an explicit opt-in desktop perception feature. It samples the selected monitor, applies foreground-window and privacy checks, and maintains a bounded text context. It is not a high-frame-rate screen recorder. Raw frames are not retained as ordinary application history.

See [Live Desktop Vision](docs/LIVE_DESKTOP_VISION.md).

### Kira Code

Kira Code is the task-oriented coding agent available from the normal Kira chat. It can inspect a selected project, plan a bounded task, edit a working copy, run supported checks, review the resulting changes, and package its output. The original project is kept separate from the working copy. Commands that can affect the host require the applicable confirmation; the runner is not a general-purpose security sandbox.

## Interface language

The first-run interface language is **English**. To use Persian, open the General/Preferences settings, choose **فارسی** in the Interface language field, and save the settings. The layout switches to right-to-left for Persian.

This preference affects the application interface only. Speech-recognition language, spoken voice, model language, and the language of conversation content are separate settings or model behaviors. A previously saved Persian preference is preserved when the application is updated.

See [Language Settings](docs/LANGUAGE_SETTINGS.md) for the implementation and persistence contract.

## Documentation

- [Documentation index](docs/README.md)
- [User Guide](docs/USER_GUIDE.md)
- [Language Settings](docs/LANGUAGE_SETTINGS.md)
- [Architecture entry point](ARCHITECTURE.md)
- [Architecture Master](docs/ARCHITECTURE_MASTER.md)
- [Module Ownership](docs/MODULE_OWNERSHIP.md)
- [Architecture Roadmap](docs/ARCHITECTURE_ROADMAP.md)

Feature-specific English sources and Persian translations are paired in the documentation index. The index also identifies legacy English-only engineering references whose Persian translations remain outstanding.

## Tests

Run the repository test suite from the project root:

```text
python -m unittest discover -s tests -t .
```

On Windows, **run_tests.bat** is also provided. Tests that require Windows-only APIs, installed speech models, hardware, or an interactive desktop must be validated in their corresponding environment.

## Platform and scope

The desktop application targets Windows 11. A passing source-level test does not by itself establish that audio devices, GPU inference, desktop capture, or the full interactive GUI work on every Windows machine. Those capabilities require runtime validation on the target system.
