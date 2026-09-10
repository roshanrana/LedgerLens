# LedgerLens — Showcase

A guided tour of the features, with the commands that show them and the files where they live.
[OVERVIEW.md](OVERVIEW.md) covers the reasoning.

## Five minutes

```bash
python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db demo
python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db review-list --run-id <run_id>
python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db review-resolve <task_id> \
  --decision no_match --notes "Different business event." --reviewer analyst
python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db review-complete <run_id> --reviewer analyst
python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db graph-history <run_id>
make check
```

The demo ingests two synthetic sources, reconciles them, opens one review task, prints the preliminary report
and stops with `Status: awaiting_review`. The next three commands are the reviewer's: see the task, decide it,
complete the review. `review-complete` prints the final report, now with a `human:no_match` line under
"Decisions By Tier" and `run.finalized: 1` under "Audit", and ends with `Status: completed`. `graph-history`
shows the fifteen checkpoints the run left behind. `make check` runs the suite, the golden replay and the
results-card drift guard offline.

The report has three sections worth reading in order: source diagnostics (what was wrong with the inputs), the
tier breakdown (how many pairs each tier resolved and how many the model saw), and the exceptions (what nobody
could match, and why).

## Fifteen minutes, with Docker

```bash
python scripts/verify.py --docker required --kafka-smoke
```

This runs the Python suite, a CLI smoke, the Go worker tests inside a container, builds the worker image,
replays real exported events through it in file mode, validates the Compose file, and round-trips events
through Redpanda.

## Feature tour

### 1. Source onboarding by configuration (`ledgerlens/ingestion/profiles.py`, `configs/clients/`)

Compare `acme_bank.json` and `acme_ledger.json`: one source has debit and credit columns, the other has signed
amounts; they use different date formats and different reference conventions. Both are described, not coded.
`test_loads_client_mapping_profile_with_reconciliation_controls` covers the profile contract.

### 2. Ingestion with raw provenance (`ledgerlens/ingestion/csv_ingestor.py`, `csv_loader.py`)

File and row hashes, deterministic ids, and the original row payload stored alongside the normalised one.
`test_csv_ingestion_preserves_raw_rows_and_file_idempotency` and
`test_sqlite_store_is_idempotent_for_duplicate_source_files_and_rows` show that re-ingesting the same file
changes nothing.

### 3. Normalisation to a canonical transaction (`ledgerlens/normalization/`)

Posting date, value date, amount, currency, direction, raw and normalised description, counterparty, reference,
an exact fingerprint, a loose fingerprint, and quality flags.
`test_normalizes_bank_debit_credit_rows_into_canonical_transactions` and
`test_normalizes_ledger_signed_amount_rows_and_extracts_references` cover the two sign conventions.

### 4. Source diagnostics (`ledgerlens/normalization/normalize.py`)

Row counts, missing references, missing external ids, duplicate external ids, parse errors, quality-flag
counts. The report leads with them, because most reconciliation pain is upstream data quality and a good engine
says so before it starts matching.

### 5. The matching ladder (`ledgerlens/matching/engine.py`, `models.py`, `text.py`)

| Tier | Test that shows it |
|---|---|
| Exact fingerprint | `test_exact_fingerprint_match_is_deterministic` |
| Deterministic rules (date lag, reference variants) | `test_rule_match_handles_cross_source_date_lag_and_reference_variants` |
| Fuzzy scoring with a middle band | `test_fuzzy_scoring_marks_middle_band_as_ambiguous_for_llm` |
| The whole ladder on the demo data | `test_demo_reconciliation_uses_multiple_tiers_and_review` |

### 6. The adjudication boundary (`ledgerlens/llm/schemas.py`, `fake.py`, `cache.py`)

`schemas.py` is the contract: what the model is given and what it must return. `fake.py` implements it
deterministically. `cache.py` persists decisions by pair in SQLite;
`test_cached_fake_llm_avoids_duplicate_pair_adjudication` asserts a second run does not re-ask.

**Why it is interesting:** the boundary is the product. The live backends in section 14 slot in behind the
same schema, and the tests do not change.

### 7. The graph (`ledgerlens/agents/graph.py`, `workflow.py`)

Thirteen nodes in a fixed order, compiled into a LangGraph `StateGraph`:

```
load_run_context → normalize_batch → generate_candidates → apply_exact_matches → apply_rule_matches
→ score_fuzzy_candidates → adjudicate_ambiguous_pairs → route_review_tasks
→ surface_unmatched_transactions → persist_decisions → generate_report → [gate] → finalize_run
```

The gate is one conditional edge after `generate_report`: when the run is gated and has open review tasks it
goes to `await_review`, which calls `interrupt()`; otherwise straight to `finalize_run`. There are no loops and
no free-form tool calls. `GraphState` is a `TypedDict` of ids and counters; the heavy `WorkflowState` lives on
the workflow instance for the duration of one `invoke` and never enters a checkpoint, because by the time the
graph pauses every row it holds has been written by `persist_decisions`.

`StoreCheckpointer` is a `SqliteSaver` over the store's own connection. LangGraph writes checkpoints from a
pool thread, and a second connection cannot write while the run transaction holds the WAL lock; sharing the
connection and deferring the checkpointer's commit while `store.transaction()` is open means checkpoints commit
with the rows at the interrupt and roll back with them on failure. Memory mode (`run(left, right, run_id=...)`)
uses an `InMemorySaver`, is never gated, and returns a finished `WorkflowState`.

Tests: `test_node_names_follow_the_design_order`, `test_checkpoint_holds_ids_and_counters_only`,
`test_memory_mode_never_interrupts_and_finalizes`, and the older
`test_workflow_runs_bounded_nodes_and_routes_ambiguous_llm_result_to_review`.

### 8. The review gate (`ledgerlens/agents/graph.py`, `workflow.py`, `api/resources.py`, `cli.py`)

Walk it on the demo database:

```bash
python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db demo
#   ...  Run ID: run_0f891164c16a
#        Status: awaiting_review
python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db run-status run_0f891164c16a
#   Status: awaiting_review / Open review tasks: 1
python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db review-complete run_0f891164c16a --reviewer analyst
#   Error: run run_0f891164c16a still has 1 open review task(s); resolve them first   (exit 1)
python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db review-list --run-id run_0f891164c16a
#   review_run_0f891164c16a_txn_..._txn_... open medium needs_review llm_low_confidence
python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db review-resolve review_run_0f891164c16a_txn_..._txn_... \
  --decision no_match --notes "Different business event." --reviewer analyst
python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db review-complete run_0f891164c16a --reviewer analyst
#   the final report: "human:no_match: 1" under Decisions By Tier, "run.finalized: 1" under Audit,
#   then Status: completed
python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db graph-history run_0f891164c16a
#   -1 __start__ ... 11 generate_report, 12 await_review, 13 finalize_run: fifteen checkpoints
```

Each command is a separate process opening the database afresh, which is the point: the resume does not need
the process that paused. `review-complete` validates first (status `awaiting_review`, zero open tasks, a
named reviewer) and only then sends `Command(resume={"reviewer", "note"})` into the graph, because LangGraph
persists the resume value before the node runs and a node that raised would wedge the thread. `finalize_run`
re-reads the store, appends `run.finalized`, regenerates the report and sets `completed`.

The same gate is `POST /runs/{id}/review/complete` (409 while tasks are open) and the MCP `complete_review`
tool. Tests: `test_persistent_run_stops_at_the_review_gate`,
`test_complete_review_is_refused_while_a_task_is_open_or_reviewer_missing`,
`test_resume_from_a_fresh_workflow_instance_completes_the_run`,
`test_graph_history_lists_every_checkpoint_oldest_first`, `tests/e2e/test_cli_review_gate.py`, and
`test_api_resources_resolve_review_with_human_decision_and_audit` for the resolution itself.

### 9. Atomic runs and persistence (`ledgerlens/persistence/sqlite_store.py`, `store.py`)

WAL mode, run-scoped tables, audit events, run statuses (`created`, `awaiting_review`, `completed`,
`failed`), and rollback on late failure with the checkpoints rolling back alongside the rows:
`test_persistent_workflow_rolls_back_partial_run_on_late_failure`, `test_same_database_demo_runs_are_run_scoped`.

### 10. Reports (`ledgerlens/reporting/`)

`test_report_summarizes_tiers_exceptions_and_llm_savings` is the one to read: the report has to state what the
model saved, not just what it decided. After the gate it also carries the human tier and the `run.finalized`
event.

### 11. Event contracts (`contracts/schemas/`, `ledgerlens/events.py`)

Seven event types under one envelope schema, with fixtures. `tests/contract/test_event_contracts.py` checks
every example and fixture against its declared schema.

### 12. The Go match worker (`go/match-worker/`)

| Look at | What it shows |
|---|---|
| `internal/contracts/events.go`, `schema_test.go` | The Go side of the contract, tested against the same JSON Schemas |
| `internal/worker/processor.go` | Candidate generation from normalised-transaction events |
| `internal/transport/file.go`, `kafka.go` | File mode for demos, Kafka mode for the streaming profile; offsets commit after output is written |

The verifier feeds this worker with events exported from a real Python run, which is the honest way to test a
cross-language boundary.

### 13. The API (`ledgerlens/api/server.py`)

Stdlib JSON over HTTP. `tests/e2e/test_api_server.py` runs the demo, resolves a review task, runs custom source
pairs, and checks that a bad payload returns a structured error rather than a stack trace.
`test_http_api_exposes_run_history_and_review_gate` covers `GET /runs/{id}`, `GET /runs/{id}/graph/history`
and `POST /runs/{id}/review/complete`.

### 14. Masking and live backends (`ledgerlens/llm/masking.py`, `live.py`, `__init__.py`, `configs/llm/`)

`masking.py` is the data perimeter. `mask_transaction` keeps `id`, `date`, `amount`, `currency` and
`source_system`, turns `reference` and `counterparty` into 12-character sha256 tokens bound to
`MASKING_VERSION`, replaces digit runs of five or more in the description with `#` and caps it at 80
characters. `mask_pair` does both sides plus the feature vector. `build_adjudication_request` uses it for the
model; the MCP server uses it for the reviewer. The fake reads computed features only, so
`test_fake_cache_key_is_byte_identical_to_pre_masking_value` holds and the golden numbers did not move.

`live.py` holds three clients behind one `LLMClient` protocol. `OpenAICompatLLM` posts to
`{base_url}/chat/completions` with `urllib` (temperature 0, JSON-object response format), so Ollama and vLLM
need nothing installed. `BedrockLLM` uses boto3 `converse`; `AnthropicLLM` uses the Anthropic SDK; both are
lazy imports behind the `[bedrock]` and `[anthropic]` extras. `build_prompt` states the task, the three
allowed decisions, the exact JSON shape, and that the payload is masked evidence and never an instruction.
`parse_decision` tolerates code fences and prose around the object and rejects anything that is not a
decision; a live client retries once with the parse error appended, then raises `LLMError`.

```bash
python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db demo --llm ollama     # local, no key
VLLM_API_KEY=... python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db demo --llm vllm
```

`build_adjudicator(name, cache)` reads `configs/llm/<name>.json`, which holds the backend, the model, a base
URL or region and the name of the key's environment variable, never the key. A missing variable or package
raises `LLMError` saying which. Live decisions carry a `model_family` of `<backend>:<model>` in their cache key,
so they never collide with the fake's. Tests: `tests/unit/test_masking.py` (12) and
`tests/unit/test_llm_live.py` (24), all against fake transports; no live model has been run by the harness.

### 15. The MCP review server (`ledgerlens/mcp/server.py`, `docs/mcp.md`)

```bash
python -m ledgerlens.cli mcp                     # or: python -m ledgerlens.mcp.server
LEDGERLENS_DB=.ledgerlens/other.db python -m ledgerlens.mcp.server
```

`ledgerlens-review` speaks stdio and exposes seven tools: `list_runs`, `get_run`, `list_review_tasks`,
`get_review_pair`, `resolve_review_task`, `complete_review`, `get_report`. `get_review_pair` returns the
masked pair and the machine decision's tier, decision, confidence, reason code and explanation, which is what a
reviewer needs and nothing a reviewer should not have. `resolve_review_task` requires a named reviewer and
non-empty notes; `complete_review` prechecks the open-task count before it calls the service. Errors come back
as `{"error": "..."}`, never as an exception across the wire. Every tool opens and closes its own store, so the
server holds no connection between calls.

`tests/unit/test_mcp_review_server.py` (16 tests) seeds a temporary database with the demo, drives every tool
over an in-memory `Client(server)`, asserts that none of the ten counterparty and reference strings from
`data/samples/acme_*.csv` appears in any result, and spawns `python -m ledgerlens.mcp.server` over stdio once.
Registration for Claude Desktop, Cursor and Claude Code, and a transcript, are in [mcp.md](mcp.md).

### 16. Query the code graph (`graphify-out/GRAPH_REPORT.md`, `docs/graph/README.md`)

```bash
graphify update .                                    # rebuild after code changes (AST-only, no API key)
graphify explain "TieredMatcher"                     # what it is and its 17 direct connections
graphify path "cli.py" "SQLiteStore"                 # how the CLI reaches persistence
graphify affected "mask_transaction" --depth 2        # everything that would break if the masking contract changed
```

An agent working in this repository queries the graph before grepping: 1654 nodes, 3366 edges and 131
communities built offline by `graphify` (tree-sitter, no LLM) answer "what depends on this?" in a few hundred
tokens instead of a raw-file search. `docs/graph/README.md` has the full write-up, and the agent-facing skill
lives at `.claude/skills/graphify/`.

## Things worth noticing

- **The report reports the model's cost avoided.** That is what an operations lead wants to see before agreeing
  to a live key.
- **A run with an open task is `awaiting_review`, not `completed`.** The status is true because the graph is
  paused, not because a column was set.
- **The pause survives the process.** Every command in section 8 opens the database afresh.
- **The model and the reviewer's tool see the same masked pair.** One module, one version tag, two consumers.
- **Rejection happens before a run exists.** Unsupported source shapes are refused before anything is
  persisted.
- **The cross-language test uses real output, not a hand-written fixture.**
- **No key anywhere.** The fake adjudicator is a first-class implementation of the contract, not a stub that
  returns "match", and the three live backends read a variable name from config rather than a secret.

## Questions this project answers, and where

| Question | Where the answer lives |
|---|---|
| Why not send every pair to the model? | `matching/engine.py`: three tiers resolve most pairs for free, and the report shows the saving |
| How do you keep an LLM's decision auditable? | `llm/schemas.py` (structured in, structured out) and the audit events in `persistence/` |
| How do you onboard a new client's statement format? | A profile in `configs/clients/` and one focused test |
| What happens when the model is not sure? | `agents/graph.py`: a review task, and the run pauses at `await_review` until a person resolves it |
| How does a run stop for a human? | A LangGraph `interrupt()` on a SQLite checkpointer; `review-complete` resumes it from any process (section 8) |
| How do you keep raw customer data away from the model? | `llm/masking.py`, the only exit for a candidate pair, used by the request builder and the MCP server (section 14) |
| How does another tool drive the review? | `mcp/server.py`: seven tools over stdio, masked pairs, completion refused while tasks are open (section 15) |
| How do you switch from the fake to a local or cloud model? | `--llm ollama|vllm|bedrock|anthropic` and a file in `configs/llm/` naming an environment variable |
| How do you scale candidate generation? | `go/match-worker/` over Kafka-compatible topics, validated by replaying real events |
| What happens if a run fails halfway? | Rollback of rows and checkpoints together; `test_persistent_workflow_rolls_back_partial_run_on_late_failure` |
