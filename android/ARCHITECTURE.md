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
  skill, search, generated-image and real-time voice lifecycle records.
- `domain/repository`: ports for chat, provider, assistant-library, search,
  image generation, image-provider settings and real-time voice sessions.
  Contracts do not import Android, Compose, HTTP clients or SQLite.
- `domain/policy`: pure model eligibility and route ordering.
- `application`: chat, provider, assistant-library, search, image generation,
  real-time voice lifecycle and navigation policy. Interactors validate inputs and
  coordinate domain ports; they do not know Android.
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
- Image: `KiraImageScreen → ImageGenerationInteractor → ImageGenerationRepository → OpenAiCompatibleImageRepository`; settings and secrets use a separate Domain port and encrypted Android Keystore adapter.
- Voice: `KiraVoiceScreen → RealtimeVoiceInteractor → RealtimeVoiceSessionFactory / VoiceCredentialRepository`; Gemini Live WebSocket, microphone and audio playback remain in Data. Typed session events carry lifecycle transitions to Application.

The composition root is the only layer that wires concrete implementations. Android
framework classes, Compose, SQLite, Android Keystore and HTTP transport must not leak
into Domain or Application.


## Image generation (Task 6)

`KiraImageScreen → ImageGenerationInteractor → ImageGenerationRepository →
OpenAiCompatibleImageRepository`

Provider settings and credentials use a separate Domain port implemented by
`ImageGenerationSettingsStore`. Application validates the HTTPS base URL, model ID,
API key, prompt length and supported dimensions before dispatch. The Data adapter
encrypts the key with AES/GCM and Android Keystore, bounds response/image sizes,
validates PNG/JPEG/WebP output, stores generated images in app-private storage and
keeps a bounded local history. UI receives only provider metadata and
`GeneratedImage`; it never reads the credential directly. Save/share uses Android
Storage Access Framework and FileProvider.

## Real-time voice (Task 7)

`KiraVoiceScreen → RealtimeVoiceInteractor → RealtimeVoiceSessionFactory /
VoiceCredentialRepository`

Application owns the call-state machine (Idle, Connecting, Connected, Muted and
Failed), credential policy, session lifecycle, retryability and stale-session event
filtering. Domain ports carry typed events (`Connected`, `Muted`, `Unmuted`,
`Failed`, `Ended`) rather than parsing localized status strings. The Data adapter
owns Gemini Live WebSocket transport, 16 kHz mono PCM capture, 24 kHz PCM playback,
acoustic echo cancellation and noise suppression. It emits `Connected` only after
the microphone is initialized and recording; microphone setup failures are typed
failures, not false successful calls. Gemini Live credentials use Android
Keystore-backed AES/GCM.
