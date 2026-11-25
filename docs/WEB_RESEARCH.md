# Kira: Web Intelligence and Multi-source Research Agent

This feature builds on the existing **Web Search, Unified Tool System, and Autonomous Agent**. It does not replace them. Existing quick/automatic search (🌐 button, `/web`, Tavily → Gemini → DuckDuckGo) continues to work as before. Only requests such as “research this”, “provide sources”, or “read this link” use the tool workflow.

## Architecture

```text
User message ──► ToolAgent.plan (no model call; new "web" category)
                    │
                    ├─ Casual chat / quick news question ─► previous one-step search path (unchanged)
                    └─ “Research / cite sources / read this link / continue research”
                           │  (existing text protocol; no Function Calling required)
                           ▼
                   Registry: web_search · web_read · web_research · web_research_status
                           │
                           ▼
                   kira/webintel
                     netguard.py  safe fetch (SSRF, size, timeout, redirects) + output privacy
                     extract.py   HTML/PDF → main text + title/publisher/date/author; instruction-injection removal
                     rank.py      deduplication, source reliability, recency, ranking
                     session.py   temporary research state + budget + stop/resume (stored in data/web_research)
                     engine.py    multi-stage search, page reading, deep research, cited report
```

- **Provider-independent:** none of the tasks (search, reading, ranking, relevant-section extraction, source comparison, report assembly) calls a model. They are all local code. The same result is produced with Gemini, OpenRouter, DeepSeek, Groq, Mistral, Cloudflare, or Ollama, and this feature consumes no model tokens. The model only reads the compact report and writes the final answer. Simple processing (compression and deduplication) is therefore done locally rather than by a local model.
- **Research state is outside the model:** changing Route, Provider, or failover does not lose progress because the model only calls a tool and state lives in `session.py`.
- **Integrated with Autonomous Agent:** web tools live in the same Registry, so the multi-step planner (`<kira_plan>`) can include them as steps (for example, “research X, then find related files”). Access levels, honest reporting, and Stop behavior remain the same.

## Tools (read-only; they do not download or execute files)

| Tool | Function |
|---|---|
| `web_search` | `kind` = `web`, `news`, `docs` (PDF and documents), or `images`. Duplicate and near-copy results are removed and results are ranked by relevance, reliability, and recency. Each result includes date, freshness, and source type. |
| `web_read` | Reads one online page or PDF: title, publisher, publication date, author, and only sections relevant to `query`. `follow_links=1..3` reads related links too. Long pages can continue with `start`. Inaccessible pages report the actual reason. |
| `web_research` | Deep Research: plans subtopics (automatically or from model-supplied `subtopics`), searches and reads several independent sources for each, fills weak subtopics with additional search, and produces a cited report. `resume=true` continues stopped research. |
| `web_research_status` | `status`, `json`, `stop`, or `clear` for temporary research memory. |

### Deep Research report

- Each claim receives one label: **✔ Corroborated** (at least two independent sites); **◐ Primary/official source**; **○ Single source**; **✎ Analysis/opinion**; **⚠ Uncertain/old**.
- Each claim has a numbered source, and the source list contains the exact link, publisher, date, freshness, and source type.
- Separate sections cover possible contradictions (different figures from independent sources), outdated information, inaccessible pages, and evidence gaps.
- The report is compressed to `web_research_max_chars` (fewer and shorter claims rather than cutting a sentence in half).
- Sources and quotations are never fabricated. The report is built only from text actually read, and answer instructions are passed to the model with it.

> **Honest limitations:** source reliability is an estimate based on site type (government, academic, news organization, reference site, social network), not a verdict that a claim is correct. “Independent” means different domains; code cannot always identify two sites copying the same story, although near-identical headlines are removed. Contradiction detection applies only to numbers. Pages rendered by JavaScript, behind login/paywall, or blocking bots cannot be read and are reported as such. Scanned PDFs without text cannot be read without OCR; PDFs require `pypdf`. Image search uses Tavily only and returns image URLs plus descriptions. Some sources have unknown dates and are labeled accordingly.

## Temporary research memory

- Search results, read page sections (relevant excerpts, not entire pages), findings, and consumed budget are retained to avoid duplicate searches/downloads.
- Time-sensitive items expire sooner and are checked again (search: 10 minutes, page: 30 minutes); other items last 6 and 12 hours.
- State is stored in `data/web_research/session.json` so it can resume after the app closes. It is valid for **24 hours**, never enters Kira's long-term/personality memory, and is removed by Clear Chat or `web_research_status` with `clear`.

## Stop and resume

- The Stop button (the same control used to stop reply generation) pauses research at the next stage. Status becomes “stopped (resumable)” and a partial report is created.
- Search/page/time limits have the same effect.
- Typing “continue research” (or “continue” when research is stopped) resumes from the saved state. Already-read pages are not downloaded again, and a fresh budget begins.

## Security

- **Prompt injection:** page text is always treated as data. Sentences that instruct an AI (“ignore previous instructions”, “run a tool”, “send the API key”, Kira tool tags, etc.) are removed before reaching the model, and their count is reported. Tool-protocol tags in results are neutralized. No instruction from a page is executed because tools still require explicit user intent.
- **Leak prevention:** a query or URL resembling a key/token/password, or containing one of Kira's stored keys, is not sent. File paths, email addresses, and internal IPs are removed from search queries. URLs containing `?token=` or `?key=` are rejected. Cookies and Authorization headers are never sent.
- **Allowed URLs only:** `web_read` opens only a URL written by the user or obtained from results/pages in the same research session; the model cannot open an arbitrary URL of its own.
- **SSRF protection:** localhost, `*.local`, `*.internal`, `*.lan`, undotted hostnames, and private/loopback/link-local/reserved IP addresses (including IPv4-mapped IPv6) are rejected. Both the initial URL and **every redirect** are checked. DNS results are checked before connection and the actual connected address is checked afterward where supported. Only ports 80, 443, 8080, and 8443 are allowed. If a system proxy/VPN is active, the proxy performs name resolution; Kira checks direct IPs and suspicious names locally. If network DNS returns a block-page IP (such as `10.10.34.x`), Kira reports that the site is blocked rather than a security error. *Limitation: without a proxy, a DNS change between validation and connection is covered only when the urllib3 version exposes the actual connection address.*
- **Resource limits:** maximum page size (`web_read_max_mb`), page timeout (`web_read_timeout` plus a 40-second total ceiling), redirect count, and allowed content types (text/HTML/JSON/XML/PDF).
- **No download or execution:** no file is written to disk or executed; a page is converted to text in memory only. Executables, archives, images, and videos are rejected. Download and execution are not part of this version.

## Settings (`settings.json`)

| Key | Default | Meaning |
|---|---:|---|
| `web_research` | `true` | Web tools enabled (they run only on explicit request) |
| `web_research_max_searches` | `8` | Maximum searches in one research session (1–20) |
| `web_research_max_pages` | `10` | Maximum pages read (1–25) |
| `web_research_max_seconds` | `90` | Maximum elapsed time (15–300 seconds) |
| `web_research_max_chars` | `9000` | Report size sent to model (2,500–14,000 characters) |
| `web_read_timeout` | `15` | Timeout for one page (seconds) |
| `web_read_max_mb` | `2.5` | Maximum page/PDF size (MB) |
| `web_max_redirects` | `4` | Maximum redirects allowed |

Tavily and Gemini Route keys are the same settings as before (Tavily → Google/Gemini → DuckDuckGo for quick search). The model may lower configured limits for an individual call, but cannot raise them above the user's settings.

## Quick usage guide

- `Research …` or `/research …` → Deep Research with a cited report.
- `Read and summarize this link: https://…` → `web_read`.
- `Check whether … is true using several reliable sources` → research and source comparison.
- `Search the latest news about …` (quick search) → the existing one-step search.
- Stop → pause and keep state; **Continue research** → resume; ask Kira for **Research status** (`web_research_status`).

## New and changed files

**New:** `kira/webintel/__init__.py`, `kira/webintel/netguard.py`, `kira/webintel/extract.py`, `kira/webintel/rank.py`, `kira/webintel/session.py`, `kira/webintel/engine.py`, `kira/tools/webtools.py`, `docs/WEB_RESEARCH_FA.md`.

**Changed (small, additive changes):** `kira/tools/builtin.py` (register web tools); `kira/tools/protocol.py` (web category and prompt rules); `kira/tools/agent.py` (tool labels, `plan.web`, Stop/clear research memory, resume reminder); `kira/main.py` (one condition: research requests use the tool path rather than one-step search; UI unchanged); `kira/websearch.py` (retain Tavily result dates); `kira/config.py` (defaults above); `README.md`; `docs/TOOLS_FA.md`.
