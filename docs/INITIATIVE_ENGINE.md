# Initiative Engine — Respectful Proactive Follow-ups

This capability allows Kira, Ren, and Mika to follow up at an appropriate time on an important topic the user previously mentioned. It is a memory-based reminder, not a claim of human awareness or emotion.

## Behavior and defaults

- **Off by default:** the user must enable **Proactive follow-up from important memories** separately for each character on the Characters page.
- **No model or Provider call:** a follow-up is built locally from a short template and a real memory quotation. It does not call an AI model or perform web search.
- **Relevant memories only:** only `event` and `promise` Moment records are candidates. Facts, jokes, summaries, empty data, and records with invalid timestamps are excluded.
- **Recency and due dates:** a memory must be no more than 10 days old. Follow-ups for “today/tonight” are deferred until the end of that day; “tomorrow/day after tomorrow” until the end of the due day; “next week” and numeric/weekday phrases in Persian or English (such as “in three days”, “in two weeks”, “next Thursday”, or “next Friday”) are deferred until the end of the due day. Short durations such as “in two hours” are also calculated with a one-hour safety margin. Day boundaries use the system's local calendar, not a fixed 24-hour duration.
- **Distant due dates:** if a due date lies beyond the 10-day recency window, the memory expires before the due date and no proactive follow-up is sent. The system must not message the user about an event that has not happened yet.
- **Spacing and limits:** at least 45 minutes must have passed since the latest user message in any character conversation; at least 4 hours must have passed since the previous proactive follow-up; and each character is limited to two follow-ups per local day.
- **Quiet hours:** local system time from 22:00 to 09:00 is a quiet period.
- **Presence requirements:** the main window must be visible and active, with the chat page in the foreground. No pending request/task, typed draft, input focus, modal dialog, microphone capture, wake mode, or audio playback may be active.
- **Silent; no synthetic user message:** a follow-up is stored only as an assistant message in the conversation. Kira does not read it aloud, and no fake user message is added to history.
- **No repeats:** a followed-up memory ID is excluded from candidates for the remainder of its retention window. Sent history is stored separately for each character; recent user activity in any character conversation recalculates the quiet period for all characters.
- **Honest persistence:** the message is first written to conversation history. Only after the durable write succeeds are the follow-up timestamp and memory ID recorded as completed.

## Architecture

- Selection and validation policy independent of the UI lives in `kira/character/initiative.py`.
- The scheduler uses the existing mood-indicator poll in `SessionController` and checks execution eligibility no more than once every 30 seconds.
- Memories are read inside `persona_memory.character_scope(character_id)`; emotional state, interaction timing, and follow-up state are maintained inside `mood.character_scope(character_id)`.
- Opt-in is stored in `character_initiative`; bounded timestamp/ID history is stored in `character_initiative_history` in application settings.
- When a profile is deleted, that character's opt-in and follow-up history are also removed. Other characters' data is left unchanged.

## Date parsing limitations

Due-date parsing supports common relative Persian/English expressions, numeric Gregorian dates (ISO and day/month/year), and numeric Solar Hijri dates (year/month/day). Solar Hijri conversion uses a one-day safety margin. An explicit but unsupported calendar format, a time without a date, an invalid date, or an ambiguous date is not converted into an immediate follow-up; the memory is excluded. Text month names and other local formats are not yet parsed exactly. Due dates more than 10 days away also expire before they become eligible.
