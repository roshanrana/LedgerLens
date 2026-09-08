# 05 — LangGraph orchestration, the review gate, live backends and the MCP review server

**Status:** approved 2026-09-08 (owner instruction: build autonomously; see decisions at the end)
**Extends:** `01-high-level-design.md` §6.4 and `02-low-level-multi-agent-design.md` §5, which
specified LangGraph with human-in-the-loop interrupts. The 0.1 code shipped a hand-rolled
node loop, a deterministic fake adjudicator only, and review tasks without a gate. This
document closes that gap. Interfaces in §3–§6 are frozen contracts for the parallel tasks.

## 1. What changes

| Area | 0.1 | 0.2 |
|---|---|---|
| Orchestration | `for node in node_names: node(state)` | LangGraph `StateGraph` compiled with a `SqliteSaver` checkpointer on the run database |
| Human review | tasks persisted, run marked `completed` immediately | graph `interrupt()` at `await_review`; run is `awaiting_review` until a reviewer resolves every task and completes the review, from any process |
| Adjudicator | `DeterministicFakeLLM` only | same contract, plus `openai_compat` (Ollama, vLLM), `bedrock`, `anthropic`; fake remains the default and drives the gate |
| Data perimeter | `compact()` sent verbatim | `ledgerlens.llm.masking` applied to every payload that leaves the engine |
| Review surface | CLI and JSON API | plus an MCP server (`ledgerlens-review`) exposing masked pairs and the gate to any MCP client |
| Gate command | `make test`, `make golden-check`, `make card-check` separately | `make check` runs all of them; CI runs `make check` |

Everything that made 0.1 honest stays: the matching engine is stdlib-only, runs are atomic up
to the interrupt, the golden harness replays the acme pair offline with a fixed seed and the
results card is regenerated from `metrics/headline.json`.

## 2. Graph

```
START → load_run_context → normalize_batch → generate_candidates → apply_exact_matches
      → apply_rule_matches → score_fuzzy_candidates → adjudicate_ambiguous_pairs
      → route_review_tasks → surface_unmatched_transactions → persist_decisions
      → generate_report → [gate]
gate:  gated and review_tasks → await_review → finalize_run → END
       otherwise              → finalize_run → END
```

- `node_names` becomes the thirteen names above in that order.
- **Checkpointed state is small** (LLD §5): ids and counters. `GraphState` (TypedDict):
  `run_id, client_id, mode ("memory"|"persistent"), gated: bool, stage: str, node_trace: list[str],
  candidate_pair_ids: list[str], review_task_ids: list[str], decision_counts: dict[str, int],
  llm_budget_remaining: int, awaiting_review: bool, reviewer: str | None, review_note: str | None,
  report_markdown: str | None, finalized: bool`.
- The heavy `WorkflowState` (transactions, pairs, decisions) is **not** checkpointed. During a
  single `invoke` it lives on the workflow instance (`self._active[run_id]`); at the interrupt
  everything it holds has already been written to SQLite by `persist_decisions`.
- `await_review` calls `interrupt({"run_id", "open_review_task_ids", "preliminary_report": bool})`.
  The resume value is `{"reviewer": str, "note": str}`.
- `finalize_run` (persistent mode) re-reads decisions and review tasks from the store, appends
  a `run.finalized` audit event, regenerates the report so human decisions appear in it,
  sets run status `completed`, and returns `report_markdown`. Memory mode just marks finalized.
- **Validation happens before resume, never inside the node.** LangGraph persists the resume
  value before the node runs, so a node that raises on a bad payload wedges the thread. The
  service checks that no review task is open and that `reviewer` is non-empty, then resumes.
- Checkpointer: `SqliteSaver(sqlite3.connect(db_path, check_same_thread=False))` on the same
  file as `SQLiteStore`; `thread_id = run_id`. Memory mode uses `InMemorySaver`.
- Transactions: the persistent run's `store.transaction()` covers ingestion through
  `generate_report`; it commits at the interrupt so review tasks are visible to other processes.
  A failure before the interrupt still rolls back the whole run (existing test).
- Run status values: `created → awaiting_review → completed` (or `created → completed` when
  no review is needed).

## 3. Store additions (`ledgerlens/persistence/store.py`)

```python
def get_run(self, run_id: str) -> dict[str, Any]                      # ValueError if unknown
def list_runs(self, limit: int = 50) -> list[dict[str, Any]]           # newest first
def set_run_status(self, run_id: str, status: str) -> None             # status in RUN_STATUSES
def open_review_task_count(self, run_id: str) -> int
def get_candidate_pair(self, pair_id: str) -> CandidatePair            # rebuilt from candidate_pairs + normalized_transactions; ValueError if unknown
def db_path -> Path                                                    # property, for the checkpointer
RUN_STATUSES = ("created", "awaiting_review", "completed", "failed")
```

## 4. Masking (`ledgerlens/llm/masking.py`, written)

`mask_transaction(compact)`, `mask_pair(pair)`, `token_hash(value)`, `MASKING_VERSION`.
`build_adjudication_request` uses `mask_transaction` for `left`/`right`. The MCP server uses
`mask_pair`. Raw `counterparty`, `reference` and unmasked descriptions never appear in either.

## 5. Adjudicator backends (`ledgerlens/llm/live.py`, `ledgerlens/llm/__init__.py`)

```python
class LLMClient(Protocol):
    model: str
    def adjudicate(self, request: LLMAdjudicationRequest) -> LLMDecision: ...

class OpenAICompatLLM(LLMClient)   # Ollama, vLLM, any /v1/chat/completions; stdlib urllib, injectable opener
class BedrockLLM(LLMClient)        # boto3 converse, lazy import; extra [bedrock]
class AnthropicLLM(LLMClient)      # anthropic SDK, lazy import; extra [anthropic]

def build_prompt(request) -> tuple[str, str]          # (system, user) with the masked payload and the JSON contract
def parse_decision(text: str) -> LLMDecision          # fences tolerated; ValueError on bad shape
def build_adjudicator(name: str, cache, *, config_dir: Path = CONFIG_DIR) -> CachedLLMAdjudicator
CONFIG_DIR = ROOT / "configs" / "llm"                 # {fake,ollama,vllm,bedrock,anthropic}.json, no secrets, api_key_env names only
```

- `model_family` enters the cache key (`build_cache_key(pair, policy, model_family=...)`) so
  fake and live decisions never share cache entries. `MODEL_FAMILY` stays the fake's value.
- Live clients retry once on a malformed answer, then raise `LLMError`. They record
  `prompt_tokens` / `completion_tokens` totals in `.usage`; `CachedLLMAdjudicator.stats()`
  includes them when present.
- Missing optional dependency or environment variable raises `LLMError` naming what to install
  or set. Nothing is read from JSON but the variable *name*.

## 6. MCP review server (`ledgerlens/mcp/server.py`)

`build_server(db_path) -> MCPServer` named `ledgerlens-review`, tools:
`list_runs(limit=20)`, `get_run(run_id)`, `list_review_tasks(run_id, status=None)`,
`get_review_pair(task_id)` (masked pair + the machine decision's reason and confidence),
`resolve_review_task(task_id, decision, notes, reviewer)` (non-empty notes and reviewer required),
`complete_review(run_id, reviewer, note="")` (resumes the graph through the service; refuses while
tasks are open), `get_report(run_id)`. Errors return `{"error": "..."}`. `main()` runs stdio;
`ledgerlens mcp` starts it. mcp SDK 2.x: `from mcp.server.mcpserver import MCPServer`;
`from mcp.client import Client` accepts the server instance in tests; results expose
`structured_content`.

## 7. Surfaces

- CLI: `review-complete RUN_ID --reviewer NAME [--note]`, `graph-history RUN_ID`,
  `run-status RUN_ID`, `mcp`; `--llm {fake,ollama,vllm,bedrock,anthropic}` on `demo` and `reconcile`.
- API: `GET /runs/{id}`, `GET /runs/{id}/graph/history`, `POST /runs/{id}/review/complete`.
- `api/resources.py`: `complete_review(db_path, run_id, *, reviewer, note="") -> dict`,
  `graph_history(db_path, run_id) -> list[dict]`, `get_run(db_path, run_id) -> dict`.

## 8. Metrics

`metrics/golden.py` gains: the replay runs to the interrupt, resolves the open review task as
a human, completes the review **through a second workflow instance on the same database**, and
scores the final report. New KPI `review_gate` ("1 / 1 gated runs resumed after review"), and
facts: LangGraph checkpoints written, review gate resumed cross-instance, MCP tools exercised
over an in-memory client, masking applied (fields redacted), live backend rows pending.
`metrics/card.json` `kpi_order` gains `review_gate`. `data/golden/expected_summary.json` is
unchanged; the golden checks run against the preliminary report exactly as before.

## 9. Tests

unittest, offline. New: `tests/unit/test_graph_gate.py` (interrupt reached, status
`awaiting_review`, resume refused while a task is open, resume in a fresh workflow instance
completes the run, human decision in the final report, checkpoint history ≥ 13 snapshots,
memory mode never interrupts), `tests/unit/test_masking.py`, `tests/unit/test_llm_live.py`
(fake opener / fake SDK clients, retry, errors, cache-key family separation),
`tests/unit/test_mcp_review_server.py` (in-memory Client, masking asserted, gate refused),
`tests/e2e/test_cli_review_gate.py` (CLI: demo → review-list → review-resolve →
review-complete → report contains the human decision; graph-history prints steps).

## Decisions

- **D-1** LangGraph and `langgraph-checkpoint-sqlite` become core dependencies; `mcp` too. The
  README's "dependency-free" claim is narrowed to the matching engine, which is still stdlib.
- **D-2** Checkpoints hold ids and counters only (LLD §5). The store is the record; the
  checkpoint is the cursor.
- **D-3** The gate finalises the run, it does not re-adjudicate. Reviewers resolve tasks with
  the existing tooling; `complete_review` resumes the graph so the run cannot be `completed`
  with open tasks.
- **D-4** Resume payloads are validated in the service before `Command(resume=...)`, because
  LangGraph persists the resume value before the node executes (learned in DRYDOCK).
- **D-5** Masking is one module used by both the LLM request and the MCP server; the fake
  adjudicator is unaffected because it reads computed features only, so golden numbers hold.
- **D-6** `openai_compat` uses `urllib` from the standard library so Ollama and vLLM need no
  extra install; Bedrock and Anthropic are optional extras with lazy imports.
