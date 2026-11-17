# Chat Commands & Actions

## Ownership

`kira.chat.commands` owns command definitions, aliases, registration, matching, parameter validation, permission decisions, dispatch, request/session correlation, idempotency and cooperative cancellation. It is independent of Qt, widgets, MainWindow, Providers and the Tool implementation layer.

`kira.chat.command_adapters` registers the command behaviors already present in Kira. It delegates parsing and execution to their existing owners; it does not reimplement tools or create a second permission system.

`ChatApplicationService` is the only application-facing dispatch boundary. It dispatches commands for an active request, accepts out-of-band controls for an active session, publishes command-dispatch lifecycle events through the existing Chat Events publisher, and cancels in-flight command work when a request/session is cancelled.

## Public contracts

- `CommandDefinition`: `command_id`, canonical `name`, `description`, JSON-Schema-subset `parameters`, `required_permissions`, injected `handler`, optional `aliases`, `matcher` or slash `parser`, `metadata`, and `enabled`.
- `CommandRequest`: immutable invocation with `command_id`, `name`, `request_id`, `session_id`, raw input, validated arguments, source and metadata.
- `CommandExecutionContext`: the command definition/request plus a cooperative cancellation signal.
- `CommandResult`: `command_id`, `request_id`, `session_id`, status, result/error and metadata.
- `CommandDispatch`: ordered results, handled/continue-chat state, rewritten text and merged metadata.
- `CommandStatus`: `pending`, `running`, `completed`, `failed`, `cancelled`, `rejected`.

## Registry behavior

`CommandRegistry.register()` rejects duplicate IDs, names and aliases. `set_enabled()`, `unregister()`, `get()` and `list_commands()` manage the registry without changing its dispatcher. Slash parsers handle explicit commands; text matchers handle deterministic natural-language controls. Unknown slash commands remain unclaimed so ordinary chat behavior is preserved.

Parameters are validated before permissions or handlers run. The supported schema subset includes required fields, additional-properties policy, scalar/object/array types, enums, numeric bounds, string lengths and regular-expression patterns. A command declaring permissions is rejected if no permission checker is injected or if the checker denies it. Permission-checker errors fail closed.

The idempotency key is `(session_id, request_id, command_id)`. A completed result is cached for duplicate calls; a concurrent duplicate receives a non-blocking pending result instead of executing the handler twice. Handlers may cooperatively observe cancellation through `context.cancelled` or `context.raise_if_cancelled()`. Cache size is bounded.

## Existing command adapters

| Command | Trigger | Existing owner |
|---|---|---|
| Usage report | `/usage [days]`, `/مصرف [days]` | `kira.usage` |
| Web search | `/web query`, `/search query`, `/سرچ query` | `kira.websearch` |
| Image search | `/img`, `/عکس` with an image attached | `kira.websearch` |
| Avatar body control | Existing Persian/English pose and gesture phrases | `kira.body` and the injected avatar adapter |
| Tool confirmation | Explicit confirmation/cancellation for a pending sensitive operation | `ToolAgent` / AccessManager |
| Tool task control | Status, pause, cancel, resume, add-step and change commands | `ToolAgent` / task store |
| Running task control | Status, pause, cancel, add-step and change while a task is running | `ToolAgent` / task store |
| Fixed desktop shortcuts | Existing app/browser shortcut phrases | `kira.actions` |

Tool calls emitted by a model remain owned by `kira.tools` and its existing protocol, registry, AccessManager and ToolAgent. Commands only delegate to that system. They do not execute arbitrary shell text and do not grant permission based on model output.

## Permissions and character/session identity

The default adapter assigns `desktop.launch` to fixed desktop shortcuts. The injected application permission checker denies this capability in Competitive Safe mode. Sensitive ToolAgent actions continue to require the existing explicit user-confirmation grant bound to the exact tool arguments; the Commands registry does not replace or bypass that grant.

The registry is shared by the chat application, so Kira, Ren and Mika use the same definitions. Runtime `session_id` and `request_id` remain the command result/cancellation identities. Where ToolAgent state is character-scoped, the adapter receives `character_id` separately and delegates to the matching character-owned task/confirmation state.

Out-of-band controls typed while a task is running receive a unique command request ID and carry the active chat request ID as `parent_request_id`. They do not enter the normal message queue. Cancellation of the active chat session cancels all command invocations belonging to that runtime session.

## Events and lifecycle

ChatApplicationService publishes `command_dispatch_started`, `command_dispatch_completed` and `command_dispatch_failed` through the shared typed Chat Events publisher. Event payloads contain command IDs and statuses, not raw command arguments or sensitive handler output. The command registry is closed during MainWindow shutdown after active work has been cancelled.

## Registering a new command

Register a `CommandDefinition` with a stable ID, unique name/aliases, a small parameter schema, required permissions, and an injected handler. Use a `parser` for slash commands or a `matcher` for deterministic text patterns. Keep the handler thin: delegate to the owning feature module, return a value or `CommandOutcome`, and raise `CommandCancelled` when cooperative cancellation is observed. Add the command through the adapter factory; do not add parsing branches to MainWindow.

## Test policy for TASK 010

Unit and integration test sources are included for registry contracts and adapters. By the agreed task sequence, no tests, compile checks, Windows tests or GUI tests are run until TASK 010 implementation is complete and the combined test phase begins.
