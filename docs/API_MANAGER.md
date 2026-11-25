# API Manager (Route Page)

Open it from the ☰ menu → **Route**. The top of the page has three sections: **Add API**, **Registered APIs**, and **API Details**. The existing Routes (models and execution priority) and local Ollama configuration remain below them.

## Add API

Enter an API key and select **Add**. Kira then:

1. Checks the key's format without a network request.
2. Sends one request to the service's official model-list endpoint. This request both validates the key and retrieves the model list; Kira does not send a duplicate validation request.
3. Registers the API only if exactly one service accepts the key. Otherwise, nothing is registered and the reason is shown: `Invalid`, `Ambiguous` (more than one service), or `Unknown` (no service accepted it).

A key is never sent to services it cannot belong to:

- `gsk_` → Groq only
- `AIza` → Google AI Studio only
- `sk-apx-` → APInex only
- An unrecognized prefix → Mistral and Cloudflare only (their keys have no identifying prefix)

**Cloudflare:** If the token can read Accounts, Kira discovers the Account ID automatically. Otherwise, Kira asks for it and the Account ID field must be filled in. Account API Tokens always require an Account ID.

After registration, the service's default model is enabled if it is present in the returned catalog. For APInex, a listed free model is selected first when available. Other models appear in **API Details** and can be enabled with their checkboxes.

## Registered APIs

Columns include Provider (with the last four key characters), API Status, available models, active models, last validation, priority, and enabled state.

Actions include:

- **View Details**
- **Refresh / Rediscover Models**
- **Edit** — a replacement key is validated first; an invalid key does not replace the existing one.
- **Enable / Disable**
- **Delete**
- **Up / Down** — changes the priority of the API.

Groq, Mistral, and Cloudflare entries built into the application cannot be deleted. **Delete** clears their key and disables their routes. Added custom APIs and their routes can be removed.

A second key for the same service is registered as an additional API (for example, “Groq (2)”). The same model on multiple keys is displayed as one model in details (“also on another API”), but its routes remain separate for failover.

Up/Down changes only the order of registered APIs. It does not change the model order inside an API or the position of Ollama.

## API Details

For each model, Kira displays availability (✓ available / ✕ no longer available / Unknown), Context Window, Max Output, and Text/Vision/Tool Calling capabilities.

**If the provider does not report a value, it is shown as `Unknown` or `Not Available`; Kira does not invent numbers.** Token Usage and Remaining Quota are not available from the keys for any of the four services and are shown as `Not Available`. Rate limits are shown only when the service returns `x-ratelimit-*` headers during the latest check.

## Migration from the previous version

Keys, routes, priorities, selected models, and cooldowns remain in their existing locations; nothing needs to be entered again. Old APIs appear as **not yet validated**. Startup does not make network requests; use Refresh to validate them.

API status is stored in `api_registry` inside `settings.json`, outside the application folder, and does not contain keys. API keys continue to be encrypted with DPAPI.
