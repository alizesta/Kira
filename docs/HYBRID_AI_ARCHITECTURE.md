# Hybrid AI execution architecture

## Ownership boundaries

- `RoutePolicyEngine` is the deterministic policy boundary. It selects and orders candidates from network permission, role allowlists, vision constraints, and manual priority. It does not own provider health or transport.
- `HybridRouter` coordinates a logical turn and preserves the public chat, stream, tools, route-status, and benchmark APIs.
- `ProviderRuntimeState` is instantiated once per router by default. The application may explicitly share health, cooldown, or quota maps across a related set of session routers; this ownership is visible in `ProviderApplicationService.rebuild_session_routers`, rather than being an implicit singleton. Separate router groups do not inherit those maps. Google quota blocks are keyed by configured project scope plus normalized model; without an explicit project scope, they are isolated by provider ID and model. No process-global or persisted cooldown/quota state is used.
- `ProviderRegistry` resolves adapter factories by stable provider ID. The `ChatProvider` protocol remains the minimum common transport contract; optional native tool calling is capability-detected rather than required of every adapter.

## Execution, retry and cancellation

- A logical chat turn never replays an identical endpoint/model/credential target. `ProviderRetryPolicy` distinguishes same-target replay eligibility from failover to a distinct configured target. This avoids silently treating a permanent key/model error as transient while still permitting an independent provider to serve the turn.
- Once streamed output has been emitted, the turn is not replayed on another route; it is reported as interrupted. Cancellation stops route advancement and suppresses a response that completes concurrently with Stop.
- The router passes one read-only cancellation token combining router-level Stop and caller-owned cancellation. HTTP adapters keep JSON response bodies lazy until decode and track the active response, so `abort()` can close both JSON and SSE requests. Ollama chat and native tool calls use the same response-lifecycle approach; the transport connect/read timeout remains the upper bound while no response handle exists yet.
- Stream iteration is always closed in a `finally` path. Provider timeouts remain route-specific and are not replaced with global hardcoded values.

## Trace lifecycle

Normal chat and native tool-calling requests both establish a request-ID ContextVar before provider traffic and emit start, route, failure/decision, completion, and end events. HTTP and Gemini-native events inherit the same correlation ID. Trace records remain metadata-only; prompts, completions, and credentials are not added.

## Adding a provider

Register a factory in `PROVIDER_REGISTRY` under a stable lowercase provider ID. Implement `enabled()`, `abort()`, `chat()`, and `stream()` according to `ChatProvider`. Keep provider-specific HTTP/SSE/native protocol conversion inside the adapter. Do not add provider-specific branches to `RoutePolicyEngine`; route policy consumes provider metadata supplied by the existing route model. Providers that support native JSON-schema tools may expose `chat_with_tools()` as an optional capability.

## Gemini Native compatibility

Gemini Native remains the preferred transport for supported models. OpenAI-compatible fallback remains explicitly opt-in and only applies to a pre-response native request rejection; errors after stream content begins are never replayed through a different protocol.
