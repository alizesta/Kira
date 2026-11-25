# Kira: Multi-step Task Planning and Execution

This capability builds on the existing Tool System and Computer Awareness; it does not replace them. A simple request (one tool call or ordinary chat) follows the existing path. Only requests that appear to require multiple dependent steps use the planner.

## Workflow

1. **Decision (no model call):** A message about this computer that requests several actions in sequence (for example, “find these files, organize them, and tell me” or “move these files”) is classified as a multi-step task. Casual chat and general questions do not receive tools. Web search and memory continue to be decided separately.
2. **Planning (one model round):** The model either answers directly or emits a `<kira_plan>` block containing the goal, steps, tool for each step, dependencies, assumptions, missing information, and one question. The user does not see the raw block. Code validates the plan: unknown tools are rejected, sensitive tools always require confirmation, the number of steps is capped, and a step may depend only on earlier steps.
3. **Missing information:** If essential details are unknown (which files or which folder, for example), Kira asks one concise question. Nothing is executed until the user answers.
4. **Step-by-step execution:** Each step uses the same Registry and access level as before. After each result, **the system itself** checks whether the step's goal was actually achieved. For example, “tool succeeded but found zero files” means the step was not achieved; “an application launch command was issued but no window was observed” means the result is unconfirmed.
5. **Replanning:** If a step fails or its result differs from expectations, the model may revise the remaining steps (up to `agent_max_replans` times) or ask a question. Completed steps are retained.
6. **Honest reporting:** If the task does not finish completely and cleanly, the final answer includes a **Task status** section that reports completed, failed, and unconfirmed steps. A task with any failed step is never reported as successful.

## Error handling

- A transient failure (such as a file being in use or a timeout) is automatically retried once only for **read-only** tools. Executing and sensitive operations are never retried automatically.
- Permanent failures (access denied, unknown tool, invalid argument, missing file) are not retried; the model must choose another route or ask the user.
- A call with identical arguments is blocked after two failures. A successful operation is not executed again.
- Model rounds and tool executions are bounded by `agent_max_steps`.

## User controls during a task

| User message | Effect |
|---|---|
| “Task status”, “How far have you got?”, “How much is left?” | Immediate progress report without a model call, including during execution |
| “Wait” / “Stop” | Stop after the current step and preserve task state; the Stop button does the same |
| “Continue” | Resume from the same step; failed steps get one further attempt |
| “Cancel task” | Cancel the task |
| “Add a step: …” | Add a step to the plan |
| “No, do … instead” / “Change the goal” | Adapt the plan to the new request while retaining useful completed results |
| Answer Kira's question | Continue the task using that answer |

Sensitive actions (delete/move) still require explicit confirmation. A confirmation applies to one operation only; the next sensitive step requires another confirmation. After confirming, type **Continue** when further steps remain.

## Task state and recovery

State is stored in `kira_tasks.json` alongside user data. If the application closes mid-task, the task is marked **paused** on the next launch. Use “Continue” or “Task status” to return to it. A pending confirmation is never carried from one run to another.

**Persisted:** short goal, steps and their status, one-line result summaries, errors, assumptions, and open questions.

**Not persisted:** file contents, complete tool outputs, raw arguments or paths (only a call hash), or credentials. Secrets are redacted before storage. After 24 hours, an unfinished task is labeled as potentially stale. **Clear chat** also clears tasks.

## Memory

- The planner prompt receives the same long-term memory (preferences and user information).
- An explicit preference about how work should be performed (for example, “always ask before deleting”) is saved as a short persistent memory note.
- Tool results are never written to long-term memory.
- Task state separates **verified facts** (summaries of actual tool results), **temporary data** (available only during this run), and **assumptions** (model hypotheses, not facts).

## Provider independence

The planner uses the text protocols `<kira_plan>` and `<kira_tool>`; Function Calling is not required. The same protocol works with Gemini, OpenRouter/DeepSeek, Groq, Mistral, Cloudflare, and Ollama. Task state is stored outside the model and added to each round's prompt, so a route change (failover) does not lose previous steps or results.

Changing the model does not grant additional access. The Registry, not the plan, determines permissions.

## Settings (`settings.json`)

| Key | Default | Meaning |
|---|---:|---|
| `agent_planning` | `auto` | `auto` plans multi-step requests; `off` uses only the previous simple tool loop |
| `agent_max_steps` | `8` | Maximum steps in one task (2–15); tool executions are capped at twice this value |
| `agent_max_replans` | `3` | Maximum plan revisions in one task (0–5) |
| `tools_max_rounds` | `4` | Existing limit for tool rounds in simple requests |

## Examples

- “Check drive A, find large files, and tell me what is using the most space”: inspect drives → find large files → sort and compare → report.
- “Find the Kira project's PDF files and sort them by date”: search permitted folders → inspect dates → return a sorted report.
- “Move these files to the project folder”: if the files are unclear, ask; inspect the destination; explain exactly what will happen and request confirmation; then verify the files in the destination.

## Limitations and unimplemented items

- Planning quality depends on the model. Small local models may produce an invalid plan block; after one correction, the previous simple loop continues.
- Multi-step planning adds one model round and roughly 2,000–3,000 characters to the prompt, which can matter with small Ollama Context windows.
- Multi-step classification and control commands (“Task status”, “Continue”) are rule-based and may sometimes be wrong. In the worst case, the model decides not to create a plan.
- After confirming a sensitive step, later steps do not run automatically; the user must type “Continue”.
- Messages typed during execution remain queued as before, except for the control commands listed above.
- Only existing tools can be planned. This does not add a free shell, full Windows control, or permanent background execution.
- To add a tool, implement a function and register it in `kira/tools/builtin.py`; the planner can then recognize it.
- The source note for this feature stated that it had not been run with real Windows and providers; it explicitly said no tests were created or executed for that development stage.

## Developer map

`kira/tools/tasks.py` (plan, state, persistence, result verification, error classification, user controls) · `planner.py` (the `<kira_plan>` protocol, validation, prompts, multi-step detection) · `autonomy.py` (planning/execution/replanning loop and mid-task controls) · `agent.py` (the prior simple loop and integration with the planner).
