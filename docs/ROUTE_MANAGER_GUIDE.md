# Route Manager Guide

Open it from the ☰ menu → **Route**.

## Concepts

- **API / Provider:** a connection with a key (Groq, Mistral, Google AI Studio, Cloudflare, OpenRouter, or a custom provider) or local Ollama. Add APIs with **Add API** at the top of this page; see `API_MANAGER.md`.
- **Route:** one model on one Provider. Each Route has its own settings and priority.
- **Priority is list order.** The upper Route is tried first. If it fails, failover moves to the next one.

## Common tasks

| Goal | Action |
|---|---|
| Change order | Drag and drop a Route, or use ▲ / ▼ |
| Temporarily disable a model | Select the Route and untick **Enabled**; its settings remain |
| Choose the default model | Select the Route and choose **Default**; it moves to rank 1 |
| Use a specific model now | Select **Manual use** on the Route, or click the indicator beside the message field. Return to **Automatic** to restore auto selection |
| Check model health | **Test Connection** (may consume some API quota) |
| Compare model speed | **Benchmark this Route** or **Benchmark all enabled** |
| Discover installed Ollama models | **Discover Ollama Models**; new routes are disabled until enabled manually |
| Disable failover | Untick **Failover**; only the manually selected Route is attempted |

## Route settings

- **Timeout:** maximum wait. Cloud: 5–60 seconds (default 18); local: 10–600 seconds (default 180).
- **Cooldown after error:** how many seconds the Route is skipped after a temporary network/timeout/5xx error (default 45; 0 means retry immediately). A 429 error uses at least 30–600 seconds according to Retry-After. Key/model errors cause a 60-second cooldown. Saving settings or making a manual selection clears cooldowns.
- **Context / Num Predict** (Ollama only): 0 means use the Provider default. Note: if two Routes use the **same model** with different Context values, Ollama reloads the model when switching between them.

## Health status

- `— Not tested`
- `● Healthy` — latest request/test succeeded.
- `◐ Temporary issue` — timeout/network/5xx.
- `✕ Unavailable` — invalid key/model or Ollama is stopped.

Health status is stored in memory only and is cleared after restart.

## Model indicator

Before sending, it shows the model that will be tried **first**. During generation it shows the actual model. After completion it shows the final model used (the replacement model when failover occurred). Click the indicator for details or manual selection.

## Saving

The Route tab saves automatically. An empty API-key field means **keep the previous key**.
