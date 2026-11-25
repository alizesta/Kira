# Add a Provider and Model

## Add a model to an existing provider

For example, to add another model to Groq:

Route tab → **Add Route** → select the provider → enter the exact Model ID (for example, `openai/gpt-oss-20b`) → confirm.

The existing provider API key is reused. If the same model is already registered for that provider, Kira reports an error.

## Add a new provider

Any service compatible with OpenAI Chat Completions can be added:

Route tab → **Add New Provider** at the bottom of the page, then enter:

- **Name:** any label; it appears in the route indicator.
- **Base URL through `/v1`:** examples: `https://api.together.xyz/v1`, `https://api.deepinfra.com/v1/openai`, or `http://localhost:1234/v1` for LM Studio.
- **API Key:** required for a cloud service. Leave it empty for a local server and enable **Local server**.
- **First Model ID:** optional; models can be added later.

Select **Test Provider Connection**. Kira sends requests to `Base URL/models` and `Base URL/chat/completions`.

To remove a provider, use **Delete Provider**; its routes are removed as well. Built-in providers are disabled rather than deleted.

## Cloudflare

An **Account ID** is required in addition to the API token. A model ID may look like `@cf/meta/llama-3.1-8b-instruct`.

## Ollama

1. Run `ollama pull qwen3.5:4b` (or use `download_model.bat`).
2. Open the Route tab and select **Discover Ollama Models** to create a route for every installed model. Newly discovered routes are disabled.
3. Enable and order the routes you want. The Ollama address and default Context/Keep-alive settings are in the Assistant tab.

**Gaming note:** each enabled local model may use RAM or VRAM. Keep only the model you need enabled and use a short Keep-alive period.

## Add or replace an API key

Enter the new key in the API Key field and leave the field (Enter or Tab). The key is encrypted and saved automatically.
