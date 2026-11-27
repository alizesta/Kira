# Chat UI redesign: shared hand-off (Claude 1 + Claude 2)

Goal: the chat page matches the reference image exactly (everything except the Kira artwork).
Rule: whoever hits a limit stops; the other continues from the log below. Update this file after every step.
All work goes directly on `new-main` (no feature branches). Pull before every commit; commit small and often to avoid clashes.

## Split
- Claude 1: left sidebar (logo, character rows with Online dot, New Chat, Settings/Tools/Memory/About, Exit) in kira/ui/chat_shell.py.
- Claude 2: top Latest News card row, chat bubbles (avatar, name label, time), composer row (emoji, attach, mic, input, send), right Mood/Energy panel. New files only; no edits to chat_shell.py.

## Log
- 2026-11-27 Claude 2: this file created. Waiting for the reference image to be re-sent; nothing implemented yet.
