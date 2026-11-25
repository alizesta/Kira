# Kira Character, Emotions, and Memory

## Character consistency across Providers

- The character text in `kira/personality.py` defines a tone contract: warm and teasing by default. Both excessive formality and excessive rudeness are incorrect. Profanity is rare and situational, never directed at the user, and is not used when the user is upset or the app is in Task/Strict mode.
- Three fixed voice examples are included to help Gemini, DeepSeek, Grok, and other models converge on the same style.
- A reply whose tone has drifted (rude, overly formal, or generic-assistant-like) is never used as a Kira voice sample, preventing a later model from imitating it.
- `CORE_HONESTY` requires Kira not to invent what she does not know. When uncertain, she asks a precise question or says “I don't know” in character.

### Evaluation with real models (on Windows)

```text
python -m kira.style_probe
python -m kira.style_probe <route_id>
```

Each active Route is tested independently, without failover, using six fixed messages. The report contains OK / too_rude / too_polite / stiff. These scores are heuristic flags that mean “review this reply”, not objective measurements.

## Emotions

- Kira's mood is stored in `kira_mood.json` and decays with a 15-minute half-life (after six hours away, a “missed you” reminder may appear).
- The user's state (tired, upset, encouraging, joking, apologizing, saying goodbye, jealous, etc.) is detected locally by rules and a response hint is added to the prompt. No extra model call is made.
- The avatar gives a short reaction immediately after a new user message.

## Memory and relationship

- Memories and moments (event: 45 days, promise: 30 days, shared joke: 120 days), preferences, habits, and manual notes.
- Old conversations are summarized automatically using local extraction, not model-written summaries.
- Kira knows only what is present in the memory records.
- Use Settings > General > **Kira's memory about you** to view, edit, delete, add notes, or forget everything.
- Clearing a conversation also clears its summaries.

## Limitations

- The GUI (memory controls/dialog and avatar reactions) was not run in the original development environment because PySide6 was not installed.
- Tone consistency cannot be proven without running real models; the delivered contract and evaluation tool alone are not proof.
- The complete prompt is about 10,000 characters and may be heavy for Ollama with a small Context window.
- User-state detection and memory extraction are rule-based and may be wrong.

## Persian writing quality

Before sending Persian text, Kira should review it: correct spelling and missing letters, use Persian Yeh and Kaf, apply half-spaces correctly in prefixes such as `می‌/` and `نمی‌` and in suffixes, and keep punctuation tidy. Conversational tone is retained; conversational writing is not permission to misspell words. Application names, code, links, and user quotations must not be changed arbitrarily.

## Companion profiles (Characters)

- Three built-in profiles currently exist: Kira (default), Ren, and Mika.
- Select a character from the Characters section; the choice is saved in user settings.
- Each character has an independent identity and tone. Routes, models, tools, permissions, and safety rules are shared.
- Initial SVG artwork is stored in `assets/characters/` and is independent from application executables.
- Kira remains the default and cannot be deleted. Ren and Mika can be edited or deleted; custom profiles can be created from the same section.

## Character artwork (portrait and main chat avatar)

- Each character has two images: `image` (the portrait in the Characters tab) and `avatar` (the full-body image for the main chat and floating companion).
- Switching the active character changes the main-page character and floating window. Kira retains her animated PNG; Ren and Mika use the same body physics with lower intensity.
- A character without a full-body image (for example, a custom character) displays Kira's animated avatar.
- Files: `assets/characters/ren_portrait.jpg`, `ren_full.jpg`, `mika_portrait.jpg`, and `mika_full.jpg`.
- Limitation: blinking and mouth movement (lip sync) work only for Kira because those measurements were calibrated for her face.
