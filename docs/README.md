# Kira Documentation

This directory contains the technical and operational documentation for Project Kira.

## Language policy

English is the primary documentation language. New documentation is written in English first. A Persian translation follows in a separate file using the same base name plus `_FA`, for example:

- `LANGUAGE_SETTINGS.md` — English source
- `LANGUAGE_SETTINGS_FA.md` — Persian translation

The root README follows the same rule with `README.md` and `README.fa.md`.

A number of documents in this repository predate this policy. They are preserved under their existing names and listed below with their current language. The presence of a Persian-only legacy document does not imply that an English counterpart already exists. No legacy document should be deleted merely because its translation is pending.

## Start here

- [User Guide](USER_GUIDE.md) — installation, first launch, settings, and daily workflows.
- [Language Settings](LANGUAGE_SETTINGS.md) — English default, Persian selection, persistence, and RTL behavior.
- [Architecture entry point](../ARCHITECTURE.md) — canonical architecture references.
- [Architecture Master](ARCHITECTURE_MASTER.md) — current subsystem boundaries and composition.
- [Module Ownership](MODULE_OWNERSHIP.md) — ownership and dependency contracts.
- [Architecture Roadmap](ARCHITECTURE_ROADMAP.md) — confirmed technical debt and ordered engineering work.

## English technical documents

### Architecture and engineering
- [Application Feature Lifecycle](APPLICATION_FEATURE_LIFECYCLE.md)
- [Architecture Implementation Handoff](ARCHITECTURE_IMPLEMENTATION_HANDOFF_2026-11-18.md)
- [Architecture Master](ARCHITECTURE_MASTER.md)
- [Architecture Roadmap](ARCHITECTURE_ROADMAP.md)
- [Domain and Application Boundaries](DOMAIN_APPLICATION_BOUNDARIES.md)
- [Module Ownership](MODULE_OWNERSHIP.md)
- [Shared Skills](SHARED_SKILLS.md)

### Chat and persistence
- [Chat Application Service](CHAT_APPLICATION_SERVICE.md)
- [Chat Attachments](CHAT_ATTACHMENTS.md)
- [Chat Commands](CHAT_COMMANDS.md)
- [Chat Conversation Lifecycle](CHAT_CONVERSATION_LIFECYCLE.md)
- [Chat Events](CHAT_EVENTS.md)
- [Chat Organization](CHAT_ORGANIZATION.md)
- [Chat Search and Retrieval](CHAT_SEARCH_RETRIEVAL.md)
- [Chat Transfer](CHAT_TRANSFER.md)
- [Chat Transfer File Adapter](CHAT_TRANSFER_FILE_ADAPTER.md)

### Runtime, performance, and quality
- [Idle Performance](IDLE_PERFORMANCE.md)
- [Startup Performance](STARTUP_PERFORMANCE.md)
- [QA Regression Report — Tasks 001–015](QA_TASKS_001_015_REGRESSION_REPORT.md)

## Persian technical documents

The following files are currently Persian-language documents. They remain available as-is; English counterparts should be added before any source document is rewritten or retired.

### Application and agent
- [Active Mode](ACTIVE_MODE_FA.md)
- [Agent](AGENT_FA.md)
- [File Agent](FILE_AGENT_FA.md)
- [MCP Agents](MCP_AGENTS_FA.md)

### AI, model, and routing
- [Add a Provider and Model](ADD_PROVIDER_AND_MODEL_FA.md)
- [API Manager](API_MANAGER_FA.md)
- [Brain](BRAIN_FA.md)
- [Gemini Live](GEMINI_LIVE_FA.md)
- [Ollama Storage](OLLAMA_STORAGE_FA.md)
- [Route Manager Guide](ROUTE_MANAGER_GUIDE_FA.md)

### Character, emotion, and memory
- [Character](CHARACTER_FA.md)
- [Character Decision Engine](CHARACTER_DECISION_ENGINE_FA.md)
- [Character Profiles](CHARACTER_PROFILES_FA.md)
- [Emotional Runtime](EMOTIONAL_RUNTIME_FA.md)
- [Emotional State](EMOTIONAL_STATE_FA.md)
- [Emotion-driven TTS](EMOTION_DRIVEN_TTS_FA.md)
- [Initiative Engine](INITIATIVE_ENGINE_FA.md)
- [Memory Evidence](MEMORY_EVIDENCE_FA.md)

### Desktop, vision, voice, and tools
- [Desktop](DESKTOP_FA.md)
- [Live Desktop Vision](LIVE_DESKTOP_VISION_FA.md)
- [Local Voice](LOCAL_VOICE_FA.md)
- [Sentence Speech](SENTENCE_SPEECH_FA.md)
- [System Access](SYSTEM_ACCESS_FA.md)
- [Tools](TOOLS_FA.md)
- [Vision](VISION_FA.md)
- [Voice Route](VOICE_ROUTE_FA.md)
- [Web Research](WEB_RESEARCH_FA.md)
- [Windows Control](WINDOWS_CONTROL_FA.md)

### Releases, migration, and UI
- [Application Launch](APP_LAUNCH_FA.md)
- [Audio Manager](AUDIO_MANAGER_FA.md)
- [Avatar Motion — Task 2](AVATAR_MOTION_TASK_2_FA.md)
- [Changes and Integration](CHANGES_INTEGRATION_FA.md)
- [UI Motion Foundation](UI_MOTION_FOUNDATION_FA.md)
- [Usage and Cost](USAGE_FA.md)
- [Version Metadata](VERSION_METADATA_FA.md)
- [Windows 11 Checklist](WINDOWS11_CHECKLIST_FA.md)

## Other reference files

- [Kira MCP example configuration](kira_mcp.example.json)

## Documentation maintenance rules

1. Write the complete English document first.
2. Translate the approved English content into Persian in the matching `_FA.md` file.
3. Keep headings, section order, links, technical identifiers, file paths, commands, limits, and warnings aligned between both languages.
4. Do not translate code identifiers, configuration keys, command names, API names, or literal file paths.
5. When implementation changes, update the English source and its Persian counterpart in the same change set.
6. Do not claim a feature is implemented unless the source code or a test supports that statement.
7. Preserve historical reports as historical snapshots; do not silently present old test results as current verification.
