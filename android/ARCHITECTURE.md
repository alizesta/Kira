# Kira Android application architecture

Kira Android is a native client and a modular monolith. Its structure follows the
same separation used by the Windows application: a thin entry point, one explicit
composition root, application use cases, domain contracts and replaceable data adapters.

## Runtime composition

`MainActivity` is an Android entry point only. It handles the Activity lifecycle,
incoming overlay intents and installs Compose content. It does not construct databases,
providers, search clients or feature services.

`KiraMobileApplication` owns the process-scoped `KiraContainer`. The container is
the Android Composition Root and wires shared application services to data adapters.
It is lazy and synchronized so Activities and screens reuse the same instances.

## Layers

- `domain/model`: platform-independent values such as ProviderConnection,
  ProviderDiscovery, InternetSearchResponse and InternetSearchSource.
- `domain/repository`: ports for provider settings/discovery and Internet Search.
  These contracts do not import Android, Compose, HTTP clients or SQLite.
- `domain/policy`: pure model eligibility, free-model validation and route ordering.
- `application`: ProviderApplicationService and InternetSearchInteractor. These
  own input validation, model selection policy, evidence normalization and the
  bounded source context sent to Chat. They have no Android or UI dependency.
- `data/local` and `data/remote`: SQLite/Android Keystore adapters, provider
  endpoint catalog, Tavily HTTP transport and raw-content extraction.
- `KiraApplicationRoot.kt` and feature screens: Compose rendering and user actions.
  They call application services through the injected KiraContainer; they must not
  call provider endpoints or persist credentials themselves.

The current LocalKiraCore remains a compatibility persistence/runtime adapter for
existing Android functionality. Provider UI and Search UI no longer call it directly.
Do not move Android Keystore, Context, SQLite, HttpURLConnection or Compose types into
Domain or Application.

## Provider flow

`KiraRouteScreen → ProviderApplicationService → ProviderRepository →
LocalProviderRepository → LocalKiraCore`

The adapter uses the existing encrypted local provider-key vault and persisted
provider/model catalog. Provider discovery verifies the live model endpoint. Only
models admitted by FreeModelPolicy are available for selection; OpenRouter discovery
also requires zero prompt and completion pricing. The application service owns
connection validation, recommended-model selection, explicit selection, enablement
and failover ordering.

## Internet Search flow

`KiraSearchScreen → InternetSearchInteractor → InternetSearchRepository →
TavilySearchRepository`

Search credentials are encrypted with AES/GCM using a key held by Android Keystore.
The remote adapter requests Tavily raw Markdown content, applies response and timeout
limits, and rejects non-HTTPS or credential-bearing source URLs. The application
service normalizes titles/excerpts/content, assigns stable citation numbers and creates
a bounded evidence block explicitly marked as untrusted external material. Chat receives
that evidence together with inline citation markers such as `[1]`; source URLs remain
available to open from the result list.

## Dependency direction

UI → Application → Domain contracts ← Data adapters

The Composition Root is the only layer that knows concrete implementations on both
sides. Domain and Application must not import Android framework classes or UI code.
