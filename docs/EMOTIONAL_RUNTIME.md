# Kira Emotional Runtime Architecture

## Design principle

The emotional engine is independent of Providers and language models. A model may suggest an emotion for a reply using a tag, but Kira itself computes persistent state, intensity, decay, relationship, and memory.

## Layers

- **Emotion:** momentary and persistent emotions with intensity from 0 to 100 and independent gradual decay.
- **Behavior:** the style used to express a reply, such as playful, teasing, gentle, quiet, stubborn, and focused. Behavior is not the same as emotion.
- **Energy:** conversational capacity, interaction cost, and recovery while idle.
- **Relationship:** trust, closeness, familiarity, comfort, and tension. Changes are small and gradual; the system is not designed to punish the user or create dependency.
- **Emotional memory:** stores only events with a strong emotional signal; a short event history is kept separately.
- **Events:** application and avatar events are sent to the Runtime independently of Route or Provider.
- **Director/Avatar:** EmotionDirector remains responsible for frame-by-frame animation. Runtime supplies persistent state, and the avatar reacts to its snapshot.

## Persistence and compatibility

The new file is `kira_emotional_state.json` in DATA_DIR. On first use, the older `kira_mood.json` state is imported conservatively. The legacy file is neither deleted nor overwritten.

## Contracts

- No API keys or sensitive information are stored in emotional memory.
- Runtime failure must not stop chat.
- Strict mode adds no emotional context to the prompt.
- Emotion combinations and conflicts are read from the shared Emotion Library used by the Avatar Engine.
- Route Manager and Providers have no direct authority to change the character.

## Emotional continuity across a conversation

- The latest user message is passed to the current Runtime so that emotional memories relevant to the topic can be retrieved.
- When a topic is known, a memory with no topical overlap is not added to the prompt. Without a query, the previous importance/recency behavior is retained.
- Kira's reply and its emotion tag are passed to Runtime; only replies with strongly negative emotion are recorded as emotional memories.
- The structured snapshot is the source of truth for state, energy, and behavior in the prompt. The older guidance is only supplementary description and situational signal, preventing contradictory duplicate snapshots.
- An emotion tag at the start of a stream changes only the avatar's current emotional presentation. The completed reply is recorded only after the stream finishes.
- Intentional stop or generation failure clears the reply-start event and incomplete emotion. The failure event still receives its own error reaction.

## Current limitations

User-state detection is still primarily based on local rules and text, not deep multimodal analysis. Relationship and energy are lightweight configurable models, not claims of human psychological simulation. A settings panel exposing every layer and dedicated animations for every emotion are future work.

- Incomplete, cancelled, or interrupted messages do not train character or emotional memory. Fixed local replies do not change voice or mood.
- Emotional memories include speaker provenance. A query with no effective tokens retrieves nothing, and memories are excluded after their retention period.
- Corrupt memory records are validated at load time; mood update errors are logged.
- Corruption in one JSON section (emotion, behavior, relationship, traits, or feedback) does not reset other healthy sections. Future timestamps are clamped to the current time.
- Assistant messages train memory and mood only when complete and when observation has not been disabled.
- Assistant-message observation is enabled only for complete status. The `save_message` path is tested to ensure the gate runs before memory is called. Cancelled/interrupted messages and local replies are excluded from memory training.
- Default retention is 45 days for user-interaction memories and 90 days for Kira reply emotion memories. Repeated reinforcement refreshes a memory's retention period.
