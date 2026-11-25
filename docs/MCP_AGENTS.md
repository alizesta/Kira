# MCP Servers and Independent Agents

Code: `kira/mcp/` (`config.py`, `client.py`, `hub.py`, `agents.py`). No new dependency; only the Python standard library is required.

## Setup

1. Create `kira_mcp.json` in Kira's data directory (beside `settings.json`). Example: `docs/kira_mcp.example.json`.
2. Restart the application. If the file is absent, nothing happens. To disable the feature completely, set `"mcp_mode": "off"` in settings.
3. In chat, type **MCP status** to have `mcp_info` show errors.

## MCP servers

- Transport: `command` + `args` (stdio) **or** `url` (HTTP). Tools are registered in the existing Tool Registry as `server__tool`.
- **Only the user** writes this configuration file. There is no model tool for registering servers.
- Tool access level comes only from the file: per-tool `levels`, otherwise `default_level`, otherwise **sensitive** (explicit confirmation every time). Server-provided annotations such as `readOnlyHint` are ignored.
- A tool below the sensitive level runs only when the **current user message** mentions the server name or its configured `keywords`.
- A subprocess receives only the configured `env` plus a small set of system variables. API keys and `settings.json` are never passed. `shell=True` is not used.
- Requests initiated by the server back toward Kira (sampling, roots, etc.) are rejected.
- Server descriptions and outputs are sanitized, redacted, truncated, and marked as untrusted data.
- `allow`, `deny`, and `max_tools` can limit the catalog exposed to small models.
- Timeouts are not retried because the operation may already have executed. A new attempt is allowed after 30 seconds.

## Independent agents

The HTTP/JSON contract (implemented by the agent independently of Kira) is:

- `GET /health`
- `POST /ask`
- `GET /status/{id}`
- `POST /answer/{id}`
- `POST /stop/{id}`

An optional token is read from the `token_env` environment variable, not from the configuration file.

Tools: `agent_ask`, `agent_status`, `agent_answer`, `agent_stop`, `agent_health`.

- `agent_ask` is sensitive (user confirmation required), has no retry, and requires `user_quote` to be an exact substring of the current user message.
- `agent_answer` sends the agent the confirmed user quotation itself, not model-generated text. The user must explicitly approve or reject an approval request.
- Agent health is checked before delegating work (30-second cache). If the agent is not ready, no job is created.
- **Idempotency:** an open job with the same agent and same text is not created twice.
- Jobs persist in `kira_jobs.json` and survive application closure or route changes. A background poller updates their status.
- Agent output is untrusted data and cannot change permission levels.

## Limitations

- The UI does not automatically notify the user when a job finishes (the UI was not changed). Results are read when the user asks or the model calls `agent_status`.
- HTTP MCP supports JSON responses or one SSE response; OAuth is not implemented.
- Nested object/array inputs are forwarded to the server without deep validation; this is why the default access level is sensitive.

## Windows validation required

1. Run a real server through `npx` (including `npx.cmd` resolution) and verify tool registration.
2. Confirm sensitive tools require approval and read-only tools are rejected when the current user message does not name the server.
3. Close the app and verify subprocesses exit.
4. Test an example agent with `/health`, `/ask`, and job continuation after restart.
5. Measure catalog size for Qwen 3.5 4B with a small `max_tools` value.
