# Kira Character and Decision Engine

This subsystem separates character behavior from the language model and Provider. The model writes the final text; the behavioral style for each turn is selected in code.

## Layers

- **Personality Core:** stable traits are defined in `kira/character/traits.py`. Traits such as playfulness, warmth, curiosity, confidence, empathy, and care form Kira's identity baseline.
- **Emotion / Energy:** emotional state and energy come from `kira/emotion/runtime.py` and the backward-compatible facade in `kira/mood.py`.
- **Mixed emotions:** emotional components are retained together. Composite labels such as `tsundere` describe a combination and do not erase the underlying emotions. Opposing pairs are removed only when they are genuinely incompatible in meaning.
- **Relationship:** trust, intimacy, familiarity, comfort, and tension are stored in bounded form. Tension decreases slowly over time; trust and intimacy do not disappear merely because time passes.
- **Memory:** conversation memory and preferences are in `kira/persona_memory.py`. Emotional memory keeps important events, strengthens repeated memories, and retrieves relevant memories based on the current message. UI polling for memory retrieval does not mutate counters.
- **Behavior & Decision:** `DecisionEngine` combines emotion, energy, relationship, memory, and stable traits to select the dominant behavior. The result is added to the system prompt for every Provider.
- **Bounded personality learning:** Kira recognizes only explicit feedback about her own style. One message cannot change personality; at least two separate feedback signals are required. Each trait can move at most 0.12 from its baseline. Accuracy corrections may increase caution; ordinary agreement or disagreement about a topic is not treated as personality feedback.
- **Initiative Engine:** proactive check-ins require explicit user opt-in. Only recent event/promise memories (up to 10 days old) are candidates; at least 45 minutes must have passed since the last message and at least 4 hours between check-ins. Local quiet hours from 22:00 to 09:00 are enforced. The app must be visible and not in a conversation, listening, or generating a reply. Check-ins are silent and do not insert synthetic user messages into history.
- **UI status:** a small emoji indicator in the chat toolbar shows emotion, behavior, and energy. Copy/edit/read operation text is removed from messages; only icons remain.

## Safety and consistency rules

1. Momentary emotion does not overwrite stable personality traits.
2. Sensitive topics override joking and flirtation.
3. Task/strict mode prioritizes a useful answer.
4. Low energy makes behavior calmer.
5. The model must not expose internal labels or invent a memory that is absent from context.
6. Trait changes are gradual, bounded, and based on direct feedback.
7. Proactive check-ins are off by default and work only after user opt-in.
8. This phase does not change avatar appearance or design.

## Current limitations

Behavioral decisions and relevant-memory selection are deterministic code, but final text generation still depends on the language model; prompt compliance is not absolutely guaranteed. Personality learning is bounded and rule-based, not model training or free-form inference from every conversation. Emotional-memory retrieval uses token overlap, recency, and importance; this layer does not yet have its own embedding/semantic search. Simulated scenario tests measure logical consistency, not human behavior or genuine emotion.
