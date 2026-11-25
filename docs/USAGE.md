# Usage and Cost Tracking

Code: `kira/usage.py`. Database: `kira_usage.sqlite3` in the data directory, outside the application folder. Only numeric values and identifiers are stored—never prompts, replies, or API keys.

## Display

- In chat: `/usage` for today or `/usage 7` for the last seven days. No model call is made.
- Outside the app: `python -m kira.usage 7`.

## Rules

- **Tokens** are shown only when the service reports them; otherwise the value is `Unknown`. No token count is guessed from text length.
- **Cost:** `reported` (reported by the service, such as OpenRouter) is separated from `estimated` (reported tokens multiplied by a price entered by the user in `model_prices`). Otherwise, cost is Unknown. Local models are labeled “local”.
- Token sources: non-streaming responses from all services; streaming for Groq and OpenRouter through `stream_options.include_usage` (can be disabled with `usage_stream_options=false` in that provider's settings); Ollama's own counters; and a custom server only if it reports usage in its final chunk. Embedding usage is also recorded.
- Each row includes role (surface/deep/reflection/memory/embedding), provider, model, route, status, failover count/reason, connection time, first-token time, and total duration.

## Settings (`settings.json`)

```json
"model_prices": {"groq:llama-3.3-70b": {"input_per_million": 0.59, "output_per_million": 0.79}},
"usage_limits": {
  "role:deep": {"requests_per_day": 40, "tokens_per_day": 200000, "action": "block"},
  "provider:openrouter": {"requests_per_day": 200, "action": "warn"}
}
```

The price key may be `provider:model`, only `model`, or only `provider`. Prices above are examples; the user supplies the actual values and currency unit.

- `warn`: displays a warning only in `/usage`.
- `block` on a Provider: its routes are removed from failover while another usable route exists. The conversation is never interrupted.
- `block` on Deep/Reflection/Memory: the role falls back to the ordinary path or the background task is skipped. Surface receives a warning only.
- Token limits count only reported tokens.

## Limitations

- The UI was not changed. Automatic backup of `kira_usage.sqlite3` was not added because the data is reconstructable and low importance.
- Tool/web-research requests that do not call a model are not recorded.

## Windows validation required

1. Run `/usage` after several messages on each Provider; verify rows and Unknown values.
2. Test Groq/OpenRouter streaming: `stream_options` must not error and token usage must be recorded.
3. Test Ollama token counters.
4. Test `block` on a Provider with an alternative Route and with no alternative.
