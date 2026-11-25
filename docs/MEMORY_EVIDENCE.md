# Evidence-based Memory

Module: `kira/evidence_memory.py`. Data file: `kira_evidence.sqlite3` in Kira's external data directory, outside the application folder.

## What this layer does

The existing `persona_memory` remains unchanged (voice, moments, habits, summaries, and the memory-editing window). This layer adds a **source-backed fact index** alongside it:

- Each fact has a **quotation** from the user's own message and a **source message ID**. The quotation must be an exact substring of that message (after Persian normalization); otherwise, the fact is rejected and added to a quarantine table.
- Kira's own words never become “facts about the user”.
- **Contradictions and corrections:** a new value for name, age, job, city, nickname, or answer-length preference supersedes the previous value (the old record is not deleted). “I like X” and “I hate X” cancel each other. Phrases such as “No, my name is …” or “I said that incorrectly” are treated as definitive corrections.
- **Uncertainty:** phrases such as “maybe”, “I think”, and “I'm not sure” are stored as `uncertain`, retrieved with lower weight, and do not replace a definitive value.
- **Categories:** `permanent`; `temporary` and `event` (expire and are no longer retrieved); and `unverified`.

## Retrieval

- Only facts relevant to the **current message** are added to the prompt (plus up to three pinned items: name, nickname, answer-length preference, and one short interests line).
- Greetings, thanks, and one-word replies do not trigger a search.
- Retrieval uses BM25 (pure Python, with Persian normalization and character trigrams), optional embeddings, and RRF fusion.
- If the evidence layer is unavailable or unhealthy, the previous “latest facts” list is used. Memory is never silently discarded.
- Ren, Mika, and custom characters retain their previous dedicated memory files. Their own facts, moments, and summaries are ranked with Persian BM25 and the current topic. The SQLite evidence index belongs to Kira only; character information is not mixed.
- Old moments and summaries are also filtered by current-message topic, so an unrelated memory is not inserted merely because it is newer. With no query, the recent-list behavior is retained for compatibility.
- The budget is applied line by line; a fact or sentence is never cut in the middle.
- Memory-block budget is based on the Route: about 10% of `num_ctx` for a local model (minimum 800 characters) and 4,200 characters for cloud routes.

## Settings (`settings.json`)

| Key | Default | Meaning |
|---|---|---|
| `evidence_memory` | `auto` | `off` restores the exact previous behavior |
| `memory_top_k` | `6` | Maximum facts retrieved for one message |
| `embedding_backend` | `off` | `off` / `ollama` / `provider` |
| `embedding_model` | `""` | For example, `bge-m3` or `nomic-embed-text` for Ollama |
| `embedding_provider` | `""` | Provider ID for `provider`; independent of the chat Route |

Example for local Ollama: `"embedding_backend": "ollama", "embedding_model": "bge-m3"` (run `ollama pull bge-m3` first).

**Privacy warning:** with `provider`, fact text and the current message are sent to that Provider's service. The feature is off by default and is enabled only by an explicit setting.

## First-run behavior

A background thread reads chat history and creates source records for older facts (up to 3,000 messages, preserving original dates). Older facts without a source message are imported as `legacy` and do not claim to have evidence. If the user chooses **Forget everything**, current history is not learned again.

## Memory window

The UI appearance is unchanged. Deleting or editing a fact also deletes or replaces its evidence. Facts present only in the evidence layer (for example, after the 40-item limit is reached) appear in the same list with an `ev:` ID.

## Model-based fact writing (prepared, off by default)

`evidence_memory.ingest_model_facts(raw, events)` accepts a model JSON output and stores only facts whose quotations all appear exactly in the specified message. It is not called automatically anywhere at present, to avoid API usage. `WRITER_PROMPT` is prepared for the T2 Memory Decision role.

## Limitations

- Default extraction still uses the previous regex rules and may miss complex sentences.
- Semantic search runs in a thread. It has short timeouts (1.5 + 3 seconds) and falls back to word search for 60 seconds after an error.
- Like/dislike items in `persona_memory` may still both appear in the old layer; the evidence layer does not retrieve a superseded item.

Additional behavior:

- Topic retrieval for all characters uses shared BM25 and a Persian tokenizer; unrelated interests and habits are excluded from topic-specific prompts.
- An empty evidence index does not imply there are no memories; the editable legacy list is checked as a fallback.
- Budgeting follows importance order. A section that does not fit does not prevent later sections from being checked; a zero budget is truly zero.

## Learning terminology and semantic corrections from the user

- When a user message is recorded, only an explicit definition matching “phrase means meaning” is saved as a language rule. The evidence quotation must occur exactly in the message.
- The rule is stored in evidence memory with the `language_rule` label and `explicit_language_correction` source, and is retrieved into later model context through topic-based retrieval for questions about the same phrase.
- Ambiguous usage or merely seeing a term is not enough to infer and store a definition. This is online learning from explicit corrections, not model training or fine-tuning.
