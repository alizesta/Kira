# Kira Core Server

Kira Core is the shared backend for the Windows and Android clients. It is the single owner of account identity, shared settings, cloud Provider credentials, Route configuration, chat history, shared memory and cross-device restore.

The clients remain separate native applications. Device-only capabilities (Windows desktop tools, Android permissions, local model endpoints, microphone/speaker selection and screen capture sessions) remain on the device.

## Current implementation

- Email/password account registration and sign-in, with a stable provider-independent Account ID.
- Short-lived access tokens and rotating refresh tokens.
- Account-scoped settings with optimistic revision checks.
- Cloud Provider API keys encrypted at rest with Fernet; credential read endpoints return only configured/not-configured metadata.
- Shared character conversations and message history.
- Per-character account memory.
- Device registration and account snapshot/restore.
- Idempotent import of approved desktop settings, messages and memory. The server does not delete the original desktop data.
- Google Sign-In is deliberately not implemented yet. It is intended to link to the existing Account ID, not create a second Kira identity.
- Initial HTTP adapters are present in kira/core_client.py (Windows) and android/.../core/KiraCoreClient.kt (Android), including device/session token storage. The existing chat/Route/settings screens are not wired to these adapters yet.

The service is an initial backend implementation, not yet a deployed public service. Client apps do not automatically synchronize until the Core is deployed and both clients have a server URL plus account/session integration.

## Required secrets

Never commit real secrets. Keep them in server/.env or a production secret manager.

- POSTGRES_PASSWORD: database password.
- KIRA_TOKEN_SECRET: random secret of at least 32 characters, used to sign access tokens.
- KIRA_ENCRYPTION_KEY: Fernet key used to encrypt Provider credentials. Generate it once and back it up securely. Rotating or losing it requires an explicit credential re-encryption/re-entry procedure.

Generate values:

    python -c "import secrets; print(secrets.token_urlsafe(48))"
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

## Run with Docker Compose

From the repository root:

    cp server/.env.example server/.env
    # Edit server/.env and replace all CHANGE_ME values.
    docker compose --env-file server/.env -f server/docker-compose.yml up --build -d

The API listens on 127.0.0.1:8080 on the host. Put it behind a TLS reverse proxy before exposing it to the internet. The database is on a persistent named Docker volume and is not published to the host.

Check health locally:

    curl http://127.0.0.1:8080/v1/health

Interactive API documentation is available at /docs while the service is running. Do not leave interactive docs publicly exposed in a production deployment unless access is restricted.

## Run locally without Docker (development only)

    python -m venv .venv
    # Activate the environment, then:
    pip install -r server/requirements.txt

Set KIRA_TOKEN_SECRET, KIRA_ENCRYPTION_KEY and optionally KIRA_DATABASE_URL. If the database URL is omitted, the service uses a local SQLite database under server/data/ for development. Start it from the repository root:

    uvicorn server.kira_core.app:app --reload --host 127.0.0.1 --port 8080

Use PostgreSQL for a deployed service. SQLite is only the convenient local development default.

## Account restore and desktop migration

1. A client registers or signs in and receives an Account ID plus access/refresh tokens.
2. It registers its device and fetches the shared settings and sync snapshot.
3. Existing Windows data must first be previewed and explicitly approved for import.
4. Provider secrets are sent only in a separate explicit credential-transfer step and are encrypted before storage.
5. The original %LOCALAPPDATA%/Kira folder stays untouched until the import is confirmed by the user. The API never deletes local data.
6. Google sign-in, when added, must link an identity to the existing Account ID.

## API contract

The OpenAPI contract is maintained at shared/contracts/kira-core-api-v1.yaml. The Android and Windows clients must use the same contract and must not implement a second independent cloud brain.

## Current limitations

- Chat requests currently return a complete response rather than SSE streaming.
- Attachments are not stored by this initial Core implementation yet.
- Google OAuth, password reset/email verification, account deletion UI, billing and rate-limit administration are not implemented.
- The first desktop import path is an API contract and server handler; the Windows import-preview/client workflow still needs to be connected.
- Windows and Android still need their login/session UI and Core API adapters wired into their existing chat, settings and Route layers. The current adapters are the transport/session foundation, not a completed UI integration.
