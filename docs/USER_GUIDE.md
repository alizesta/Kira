# Kira User Guide

## 1. Install and launch

1. Run **install.bat** on the target Windows 11 computer.
2. Select the data directory when the installer asks. The selected directory is reused by later updates.
3. Wait for the installer to prepare the application dependencies and the configured local components.
4. Launch Kira with **start_kira.bat**.

For an update, use **update_kira.bat**. Review the update output if dependency installation or a focused test fails.

## 2. Configure an AI route

1. Open the Route settings.
2. Select **Add API** and enter the API key for a supported provider.
3. Let Kira validate the key and retrieve the provider's model catalog.
4. Add or enable a route, then choose its priority and model.
5. Save the settings.

A provider listed in the application is not automatically enabled. Keep API keys private and enter them only in the application's provider settings. See [API Manager](API_MANAGER_FA.md) and [Route Manager](ROUTE_MANAGER_GUIDE_FA.md).

## 3. Choose the interface language

The default interface language is English. Open General/Preferences settings, select **فارسی** in the Interface language selector, and save. Kira switches the interface direction to right-to-left. Select **English** to return to left-to-right.

The interface language does not automatically change speech recognition, speech synthesis, or the language of messages. Those are independent.

## 4. Chat and conversations

- Use the Chat page for ordinary conversation, questions, and supported tasks.
- Conversation history is stored separately for each available character.
- Use the new-conversation action to create a separate conversation without deleting the previous one.
- Use the history and memory controls in Preferences to manage stored conversation data.
- Character profiles share application services but retain their own conversation and presentation state.

## 5. Search and research

Use the web-search control beside the chat composer for a quick search. For a multi-source report, ask Kira to research a subject or read a supplied link. Multi-source research is distinct from quick search: it reads independent sources, compares their evidence, and reports citations, confidence, contradictions, and missing evidence.

Research can be stopped or continued. A research report is not a guarantee that every statement on the web is correct; review its sources and confidence notes.

## 6. Attach files and images

Use the attachment control, drag supported files into the chat, or paste an image from the clipboard where supported. Text and document formats are subject to the application's supported reader list. Image interpretation requires a configured vision-capable model route.

Do not attach credentials, private keys, or unrelated personal data. File access is subject to the application's local handling and permission rules.

## 7. Voice

Kira has a Gemini Live conversation mode and local speech components.

- Local speech recognition uses the selected offline ASR engine and its supported local fallback.
- Local speech synthesis uses Piper.
- Gemini Live is a separate cloud-connected mode and requires its configured provider and model.
- Microphone input and speaker output can be selected in Voice settings.

Voice engine, recognition language, and interface language are independent settings. See [Local Voice](LOCAL_VOICE_FA.md), [Voice Routing](VOICE_ROUTE_FA.md), and [Gemini Live](GEMINI_LIVE_FA.md).

## 8. Eye Mode and desktop tools

Eye Mode is off until the user enables it. It observes the selected monitor under foreground-window and privacy checks and maintains bounded context. It is a low-rate perception feature, not continuous full-frame video recording.

The Tool System exposes only supported computer-awareness and file actions. Sensitive operations require explicit confirmation. It is not an unrestricted command shell.

## 9. Kira Code

For a multi-file coding task, describe the requested project change in the normal chat. When the agent recognizes a project task, it asks for a project folder when required, inspects relevant files, proposes and executes a bounded plan on a working copy, runs supported checks, reviews the diff, and packages the result.

The agent's command runner is restricted to supported development checks. Host commands and destructive actions require confirmation. The working process is not a substitute for a separately isolated security sandbox.

## 10. Troubleshooting

- **No model is available:** check the active route, enabled provider, API key validation, model identifier, and provider connectivity.
- **Local chat is unavailable:** confirm that Ollama is running and that the configured model is installed.
- **Voice is unavailable:** check the selected engine, provider configuration (for Gemini Live), microphone permission, output device, and local model availability.
- **The interface language did not change:** select the language again, save settings, and reopen the affected page. Previously saved language preferences take precedence over the default for new settings.
- **A desktop feature is unavailable:** confirm that the feature is enabled, the target window is permitted, and the relevant Windows hardware/API is available.

## 11. Running tests

From the repository root, run:

```text
python -m unittest discover -s tests -t .
```

On Windows, **run_tests.bat** is also available. Hardware-dependent and interactive GUI behavior must be tested on a Windows desktop.
