# Kira Multi-layer Emotional System

## Purpose

Kira's emotional state is separate from her baseline personality and stable behavior. The system maintains three independent dimensions:

1. **Emotion / Mood:** dominant and accompanying emotions, with intensity from 0 to 100.
2. **Conversational Energy:** simulated conversational energy, independent of emotion and of the user's fatigue.
3. **Behavioral Disposition:** the way an emotion is expressed, such as playful, supportive, quiet, stubborn, or sulking.

This is a character simulation system; it does not claim biological state or genuine human emotion.

## Emotions

The current library has 26 IDs: the previous 24 plus `fearful` and `disgusted`. The reference list is in `kira/mood.py`; avatar reaction mappings are in `emotion_library/emotions.json`.

- Emotions are stored in `kira_mood.json` inside `DATA_DIR`.
- Emotion intensity has a 15-minute decay half-life.
- `playful` and `affectionate` have a minimum resting score so the baseline character does not become completely lifeless.
- Kira's own tagged replies also update the state.

## Conversational energy

- Initial value: 78/100.
- User-message cost: 0.55.
- Kira-reply cost: 0.35.
- Idle recovery: 0.0022 points per second, up to 100.

Levels: exhausted, tired, low, normal, active, and hyper. Energy affects reply rhythm and length only; it must not reduce accuracy or answer quality.

## Behavioral disposition

Behavioral disposition decays separately with a 40-minute half-life. Baseline behaviors include playful, affectionate, teasing, and sarcastic. Conversation events can strengthen or weaken quiet, protective, focused, sulking, stubborn, clingy, cheerful, reserved, flirty, and tsundere.

Examples:

- User expresses distress: quiet + affectionate + protective.
- User jokes: playful + teasing.
- User apologizes: affectionate increases; sulking/stubborn decreases.
- User mentions something jealousy-inducing: sulking + clingy + stubborn.

Behaviors are not absolute commands. They are independent scores interpreted together with active emotions.

## Code interfaces

- `on_user_message(text, now)`: updates user-message events, behavior, and energy.
- `on_reply(emotions, intensity, now)`: stores Kira's tagged reply emotion and behavioral disposition.
- `current(now)`: returns a snapshot compatible with the previous API, plus `secondary_emotions`, `energy`, `energy_label`, `behaviors`, and `dominant_behavior`.
- `build_block(mode_name)`: builds shared system-prompt context for all Providers. Strict mode reveals no mood data; task mode adds only the context important to response style.

## Compatibility and tests

Legacy `kira_mood.json` files containing only `scores` are still read; new fields receive defaults. No Route Manager or Provider selection behavior is changed.

Tests:

```text
python -m unittest discover -s tests -p "test_mood.py"
```
