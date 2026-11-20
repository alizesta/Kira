# Kira Android application architecture

Kira Android is a native modular monolith that mirrors the Windows architecture's responsibilities while using platform-native adapters.

| Windows responsibility | Android counterpart |
| --- | --- |
| `kira/domain` value objects | `domain/model` |
| `kira/core/interfaces` ports | `domain/repository` |
| `kira/services` application services | `application` interactors/services |
| `kira/infrastructure` adapters | `data/local`, `data/remote` |
| `kira/app/dependency_container.py` and `kira/ui/bootstrap.py` composition | `KiraMobileApplication` + `KiraContainer` |
| `kira/main.py` entry point | `MainActivity` entry point |

## Runtime composition

`MainActivity` is an Android entry point only: lifecycle and overlay intents.
`KiraMobileApplication` owns the one process-scoped `KiraContainer`, which wires
repositories, application services and transport adapters. All Compose screens receive
the root container or their use case; they do not construct databases, cores, providers,
HTTP clients or credential stores.

## Layers and dependency direction

- Domain: platform-independent chat/provider/memory/skill/search models, repository
  ports and pure policies. It imports no Android, Compose, HTTP or SQLite APIs.
- Application: chat orchestration, context building, provider eligibility/failover,
  bounded connector rounds, navigation policy, image/search/voice use cases.
- Data: local SQLite/Android Keystore adapters and remote provider/search/image/voice
  HTTP or WebSocket adapters.
- UI: Compose screens, Android Activity/service lifecycle and user interactions.
- Composition: `KiraContainer` is the only application composition root.

Chat now follows `KiraChatScreen → ChatInteractor/ChatContextBuilder →
ChatRepository + ChatCompletionGateway → LocalChatRepository + HttpChatCompletionGateway`.
Application owns user-turn persistence, free-route selection, provider failover and
connector round limits. The HTTP adapter performs exactly one provider turn. Local
SQLite stores messages/provider configuration, the encrypted credential adapter
decrypts a key only immediately before a request, and the connector adapter validates
and executes an approved read-only connector.

`LocalKiraCore` remains a compatibility data source for existing SQLite, Android
Keystore, provider catalog and skill/connector persistence. It no longer owns chat
turn orchestration, prompt composition or provider Chat HTTP. New code must use
Domain ports and Application interactors; Android-only types must not leak upward.

The Windows `kira/main.py` remains a thin entry point; desktop composition stays in
`kira/ui/bootstrap.py`, matching Android's split between MainActivity and the
application composition root.


## Android chat attachments (Task 8)

Android chat accepts up to five user-selected files per turn. Application validates
safe names, MIME allow-lists, image signatures and byte limits (8 MiB per image,
512 KiB per text file, 12 MiB total). PNG/JPEG/WebP images and supported text/code
formats are accepted; arbitrary binary files and HTML are rejected.

The local adapter persists attachment metadata in SQLite and stores bytes in the
app-private directory encrypted with a dedicated Android Keystore AES/GCM key.
The HTTP gateway creates OpenAI-compatible image data URLs or Gemini inline image
parts. Text file contents are bounded and explicitly treated as untrusted reference
data. Images are routed only to Gemini or recognized Vision model IDs.
