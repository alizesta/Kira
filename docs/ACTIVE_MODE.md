# Instruction Priority and Active Mode

## Root cause identified in the code

1. **The system prompt was entirely persona-oriented.** Seven `CORE_*` blocks (about 7,400 characters) described identity, appearance, affection, profanity and banter, user defense, and emotions. The only explicit instruction about being useful was one bullet in `CORE_IDENTITY`. There was no priority rule stating that the user's request outranks the character voice. The docstring in `personality.py` also treated identity as the highest layer.
2. **Conflicting instructions:** `CORE_LANGUAGE` asked for short, cheerful replies with no lists, while `format_hint` in `emotion/director.py` asked for usually 2–5 sentences and for the emotion Kira actually feels, not merely the topic. Those instructions are unsuitable for multi-step game guidance or troubleshooting.
3. **Voice-style memory:** `persona_memory.build_block` fed Kira's recent replies back into the prompt with an instruction to imitate their rhythm, slang, and length. Previous jokes could therefore become the pattern for the next reply, creating a self-reinforcing loop.
4. **There was no Active Mode.** Game Mode only supplied performance notes for the local model (Context and Keep-alive); it did not change response behavior. The shared chat path did not distinguish casual conversation from a practical request.
5. The default temperature of 0.7 contributed only slightly; it was not the primary cause.

Because these four issues were in shared prompt and routing layers, they could appear with any model.

## Change (minimal intervention; persona text remains intact)

- `kira/modes.py` (new): detects each message using Persian and English patterns: **chat** (full character voice), **task** (help, errors, questions, or requested work; game-related requests are also recognized), and **strict** (instructions such as “no jokes, just answer”; remains active for subsequent messages). When classification between chat and task is uncertain, task is selected.
- `personality.build_system_prompt(..., mode=)`: places an **INSTRUCTION PRIORITY** block at the beginning of the prompt (1. the request, 2. correctness and safety, 3. personality as *how* to communicate, not *whether* to do the task). An **ACTIVE MODE** block is placed at the end, after `format_hint`, explicitly overriding it while retaining the emotion tag on the first line. `mode=None` produces the previous prompt unchanged.
- `persona_memory.build_block(voice_samples=)`: recent Kira voice samples are omitted in task and strict modes.
- `main.start_worker`: detects the mode and caps temperature at 0.4 in task and strict modes. The status bar displays the current mode.
- The Assistant tab has a **Detect message mode** setting; disabling it restores the previous behavior.
