# Kira Android application architecture

Kira Android is a native client organized as a modular monolith. It mirrors the
Windows application's architectural responsibilities without importing its
Python or Qt implementation:

| Windows responsibility | Android counterpart |
| --- | --- |
| `kira/domain` value objects | `domain/model` |
| `kira/core/interfaces` ports | `domain/repository` |
| `kira/services` application services | `application` interactors/services |
| `kira/infrastructure` adapters | `data/local`, `data/remote` |
| `kira/app/dependency_container.py` and `kira/ui/bootstrap.py` composition | `KiraMobileApplication` + `KiraContainer` |
| `kira/main.py` entry point | `MainActivity` entry point |

## Runtime composition

`MainActivity` is an Android entry point only: it handles lifecycle and incoming
overlay intents, then installs Compose content. `KiraMobileApplication` owns the
single process-scoped `KiraContainer`. The container constructs the local runtime,
repositories and application services once and shares them with all screens and the
overlay service.

Screens receive the container or a use case from the root. They must not construct
`KiraContainer`, `LocalKiraCore`, databases, HTTP clients or credential stores.
This keeps one persistence/runtime instance and makes the UI a replaceable adapter.

## Layers and dependency direction

- `domain/model`: platform-independent values such as chat, provider, memory,
  skill and search records.
- `domain/repository`: ports for chat, provider, assistant-library and search data.
  Contracts do not import Android, Compose, HTTP clients or SQLite.
- `domain/policy`: pure model eligibility and route ordering.
- `application`: chat, provider, assistant-library, search and navigation policy.
  Interactors validate inputs and coordinate domain ports; they do not know Android.
- `data/local` and `data/remote`: SQLite/Android Keystore, provider endpoint
  catalog, Tavily and image/voice transports.
- `core/KiraContainer`: the sole composition root. UI calls use cases exposed here.

The current `LocalKiraCore` is retained as a compatibility runtime/storage adapter
for the existing on-device chat, skills and connector behavior. New UI and use cases
must access it only through `data/local` adapters; new business rules belong in
`application` or `domain`, never in this compatibility class. Provider HTTP and
connector execution still live in that compatibility adapter and remain an explicit
extraction boundary rather than being misrepresented as fully modularized.

## Feature flows

- Chat: `KiraChatScreen → ChatInteractor → ChatRepository → LocalChatRepository → LocalKiraCore`.
- Memory/Skills: `feature screen → AssistantInteractor → AssistantRepository → LocalAssistantRepository`.
- Providers: `KiraRouteScreen → ProviderApplicationService → ProviderRepository → LocalProviderRepository`.
- Search: `KiraSearchScreen → InternetSearchInteractor → InternetSearchRepository → TavilySearchRepository`.

The composition root is the only layer that wires concrete implementations. Android
framework classes, Compose, SQLite, Android Keystore and HTTP transport must not leak
into Domain or Application.
