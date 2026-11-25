# Multi-stage Brain (Surface / Deep / Reflection / Memory)

Code: `kira/brain.py`. Kira has one voice (character + Active Mode + memory). This module decides only how much processing each message needs.

## Roles

- **surface:** the existing ordinary request path for casual chat and simple questions. It creates no extra request and leaves the prompt unchanged.
- **deep:** the same user request, selected for demanding messages such as multi-step plans, unfinished tasks, analysis, long messages, code, or an attachment in a task context. It can use a separate route and adds one short sentence to the prompt. Nothing is added for a local model with `num_ctx ≤ 4096` (for example, Qwen 3.5 4B).
- **reflection:** runs after the reply. Free rules detect claims of completed work without a successful tool, concealed tool errors, and incorrect names. The result is only a note for the next turn: the displayed reply is never rewritten and no new user request is sent, so no loop is created. An optional `model` mode is available.
- **memory:** writes facts in the background (off by default). Every fact must be a user quotation and is verified in code.

## Settings (`settings.json`)

| Key | Default | Meaning |
|---|---|---|
| `brain_mode` | `auto` | `surface_only` never selects Deep; `off` disables the module |
| `brain_reflection` | `rules` | `model` adds one background call after a Deep turn; `off` disables reflection |
| `brain_memory_writer` | `off` | `idle` enables the background memory writer |
| `role_routes` | all `auto` | Preferred route ID for each role |
| `role_provider_allowlist` | `surface=[ollama]`, `deep=[google]`, `reflection=[google]`, `memory=[ollama]` | Hard provider boundary; failover cannot cross a role boundary |
| `role_route_models` | `surface=[kira-qwen3.5-9b-abliterated:q4_k_m]` | Exact model allowed on the local route |

## Local/cloud routing

- Surface uses Ollama only; Deep uses Google Gemini only. Manual Route selection and failover cannot bypass these boundaries.
- Explicit requests for “uncensored/unfiltered” output, adult content, several recognized sensitive topics, and equivalent English phrases prioritize the local route. The `/local` prefix forces a message to the local route even when its text also asks for “deep analysis”.
- Image input uses the Google vision route because the installed GGUF model is text-only.
- If Gemini is unavailable, a Deep request stops with an explicit error. It is not sent to Ollama or another provider.

## Safety

- The decision is deterministic code and does not call a model.
- Background calls use a second Router with a separate lock, so they do not block the user's next message. They have time/hour limits and backoff.
- Text sent to a background model passes through `redact_secrets`; API keys never enter its prompt.
- A hint is one-time, short (220 characters), sanitized, and expires after one hour or two turns.
- State is stored in `kira_brain_state.json`, not in a provider. Provider changes do not erase it.
- Any error falls back to the previous path. **Clear chat** also removes the hint.
- `brain.budget_check` is a hook for T4 cost limits.

## Telemetry

`logs/brain_telemetry.jsonl` contains metadata only (stage, reasons, rule name), not message text.

## Decision-quality update (Task 05)

- Explicit analysis and coding requests select **Deep**, even during casual chat or when a direct answer style is active. CHAT/STRICT response style no longer disables processing depth.
- A long message alone remains **surface** during casual chat, avoiding unnecessary deep processing for storytelling or open conversation.
- Persian classification normalizes half-spaces and common Arabic/Persian letter variants before checking, using the same normalizer as Mode.
- If route inspection fails or is inconclusive, Context capacity is treated as limited and the extra Deep instruction is not injected into an unknown model.
- Reflection notes are identified as untrusted, low-priority data. Instructions inside a note cannot override the current request or higher-level policies.
- Failure of one tool is not hidden by another tool succeeding in the same turn. If the first note is a duplicate, Reflection can still record a new issue.
