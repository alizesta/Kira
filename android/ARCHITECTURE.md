# Android application architecture

The Android application is a native client with its own lifecycle, persistence adapters,
permissions, presentation and device integrations. It does not depend on the Windows UI
or Windows runtime.

Feature code is being migrated incrementally toward these boundaries:

- `domain/`: platform-independent models and repository contracts.
- `application/`: use cases and feature orchestration; no Android framework dependency.
- `data/`: repository implementations and persistence/provider adapters.
- `core/`: application composition and shared runtime services.
- `ui/` and feature screens: Compose presentation only.

The first migrated vertical slice is chat. Compose calls `ChatInteractor`; the interactor
validates input and talks to `ChatRepository`; `LocalChatRepository` adapts the existing
SQLite-backed engine. The existing local storage and provider behavior remain unchanged
behind the adapter while other features are migrated.

Do not move Android permissions, AudioRecord, WindowManager, Keystore, or SQLite APIs into
the domain/application layers. Keep OS-specific behavior behind data/platform adapters.
