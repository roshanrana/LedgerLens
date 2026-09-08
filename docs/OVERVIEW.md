# LedgerLens — Overview

**What it is:** a reconciliation engine that uses a language model the way a careful operations team would use
a specialist: rarely, only for the cases that need judgement, with the question and the answer written down,
and with the run held open until a person has signed off on what the specialist was unsure about.

**Read this if** you want the problem and the design rationale. [SHOWCASE.md](SHOWCASE.md) walks the features
with commands.

---

## The setting

Every finance function reconciles. Treasury matches bank statements to the cash ledger. Operations matches
processor settlement files to the sales ledger. A fund administrator matches custodian positions to the book of
record. The files never share a schema. One side carries signed amounts; the other carries debit and credit
columns. The bank posts on Monday what the ledger booked on Friday. References are truncated, descriptions are
abbreviated differently by every system, and the same transaction id appears twice because an upstream job
re-ran.

Most rows match trivially. The cost lives in the residue: the pairs that look alike but are not, and the pairs
that are the same transaction wearing two descriptions. Historically that residue is a spreadsheet and an
analyst's afternoon. The tempting modern answer is to hand every candidate pair to a language model. It is the
wrong answer for three reasons: it costs money on every run, it cannot be explained to an auditor, and it is
slower and less reliable than a rule for the cases a rule can handle.

LedgerLens is built around the right answer: a ladder.

## The design

**Rules first, because rules are cheaper and more reliable where they apply.** Exact fingerprints catch
identical transactions. Deterministic rules catch the known finance patterns: a one-to-three-day posting lag,
reference variants, sign conventions. Fuzzy scoring over normalised descriptions, amounts and dates handles
near-misses and produces a band: high scores match, low scores become exceptions, and only the middle band goes
any further.

**A model only for the middle band, behind a contract.** The adjudicator receives a structured question (two
masked transactions, the engine's computed features, a bounded policy) and returns a structured answer (a
decision, a confidence, a reason). Its decisions are cached by pair in SQLite, so a re-run never asks the same
question twice. The report states what the model was asked, what it was not asked, and what the difference
saved.

**Humans for what the model is unsure about, and the run waits for them.** A low-confidence adjudication
becomes a review task rather than a match. In 0.1 the run was then marked `completed` with the task still open.
In 0.2 the `await_review` node calls LangGraph's `interrupt()`: the run's rows, review tasks and checkpoints
commit together, the status becomes `awaiting_review`, and nothing else happens until a named reviewer has
resolved every task and completed the review. Review resolutions carry an audit event and a `human:` decision,
and the final report shows them.

**The gate is a real interrupt, not a flag.** A status column would record that a run is waiting; it would not
make the wait resumable. The thirteen engine and gate nodes are one LangGraph `StateGraph` with a SQLite
checkpointer on the run database (`thread_id = run_id`), so the resume can come from a different process hours
later: the CLI, the JSON API and the MCP server all go through one service method that opens a fresh workflow on
the same database and resumes the thread. Checkpoints hold ids and counters only (`run_id`, candidate pair ids,
review task ids, decision counts, the remaining model budget); the transactions, pairs and decisions are never
checkpointed because they are already rows. The store is the record; the checkpoint is the cursor.

**Validation before resume, because LangGraph persists first.** LangGraph writes the resume value into the
checkpoint before the interrupted node runs again. A node that raised on a bad payload would leave the thread
wedged on that payload. So the service refuses, before touching the graph, any completion whose run is not
`awaiting_review`, whose task count is not zero, or whose reviewer is blank. `finalize_run` then re-reads the
store, appends `run.finalized`, regenerates the report and sets `completed`. It finalises; it does not
re-adjudicate.

**One data perimeter, shared by the model and the reviewer's tools.** `ledgerlens/llm/masking.py` is the only
way a candidate pair leaves the engine. It keeps id, date, amount, currency and source system verbatim, replaces
reference and counterparty with stable hashed tokens (equal tokens still mean equal values), redacts digit runs
of five or more from the description and caps it at 80 characters, and stamps a `masking_version`. The
adjudication request uses it for a live model; the MCP server uses it for a human at another tool. The
deterministic fake reads computed features only, so masking changed none of its decisions and none of the
golden numbers.

**Live backends behind the fake's contract.** `openai_compat` (Ollama, vLLM over the stdlib `urllib`),
`bedrock` (boto3 `converse`) and `anthropic` (the Anthropic SDK) implement the same `adjudicate(request)` as
the fake. A backend is a file in `configs/llm/` that names an environment variable; no key is stored anywhere.
Live clients retry once on a malformed reply and then raise; the model family is part of the cache key so a
live decision and a fake decision never share a row. The fake remains the default and drives the tests, the
golden replay and CI.

**A review server for other tools.** `ledgerlens-review` is an MCP server over stdio with seven tools: list
runs, read a run, list review tasks, read a masked pair with the machine's reason and confidence, resolve a task
(named reviewer and non-empty notes required), complete the review (refused while tasks are open), read the
report. Claude Desktop, Cursor, Claude Code or a script can drive the gate without seeing a raw counterparty or
reference.

**Atomic runs.** A run that fails before the interrupt rolls back completely, checkpoints included, because the
checkpointer shares the store's connection and defers its commits while the run transaction is open;
`test_persistent_workflow_rolls_back_partial_run_on_late_failure` proves it. Two demo runs against the same
database are scoped to their run ids and do not contaminate each other.

**Everything is an event.** Ingestion, normalisation, candidates, decisions, review, reports: each has a JSON
Schema contract in `contracts/schemas/`, and the Go match worker consumes the same events the Python engine
exports. The streaming profile is optional, but the contracts are not.

## Why a Go sidecar

Candidate generation is the part of reconciliation that scales with volume squared, and it is embarrassingly
parallel. A Go worker over a Kafka-compatible log is where that belongs in production. The worker here is small
and deliberately validated the honest way: events exported from a real Python reconciliation run are replayed
through the Go binary, and the output has to match the contract the Python side declared. Kafka offsets commit
only after candidate events are written, so a worker crash re-delivers rather than drops.

## What is measured

`make check` runs the 105-test suite, the offline golden replay and the results-card drift guard with no
network and no key. The golden numbers (6 / 6 checks, 75% match rate, 75% straight-through, 25% review
required, 12 / 12 events schema-conformant) did not move between 0.1 and 0.2; the replay scores the
preliminary report exactly as before, then resolves the open task as a human and completes the review through
a second workflow instance on the same database, which is the `review_gate` row on the results card (1 / 1).

| Claim | Evidence |
|---|---|
| Tiered matching uses every tier and routes the ambiguous band to review | `test_demo_reconciliation_uses_multiple_tiers_and_review` |
| The model never sees the same pair twice | `test_cached_fake_llm_avoids_duplicate_pair_adjudication`, `test_sqlite_llm_cache_persists_structured_decisions` |
| A gated run stops at `await_review` with status `awaiting_review` | `tests/unit/test_graph_gate.py::test_persistent_run_stops_at_the_review_gate` |
| Checkpoints hold ids and counters only | `test_checkpoint_holds_ids_and_counters_only` |
| Completion is refused while a task is open or the reviewer is blank | `test_complete_review_is_refused_while_a_task_is_open_or_reviewer_missing` |
| A fresh workflow instance on the same database completes the run | `test_resume_from_a_fresh_workflow_instance_completes_the_run`; `metrics/golden.py` does the same cross-instance |
| Every checkpoint is listed, oldest first | `test_graph_history_lists_every_checkpoint_oldest_first` |
| Memory mode never interrupts; a run with no tasks completes at once | `test_memory_mode_never_interrupts_and_finalizes`, `test_persistent_run_without_review_tasks_completes_immediately` |
| The CLI and the HTTP API walk the gate end to end | `tests/e2e/test_cli_review_gate.py` (demo, review-list, review-resolve, review-complete, graph-history; `GET /runs/{id}`, `/graph/history`, `POST .../review/complete`) |
| No raw counterparty or reference reaches the model | `tests/unit/test_masking.py::test_request_carries_no_raw_counterparty_or_reference` |
| Masking changed nothing the fake sees, so its cache keys are byte-identical | `test_features_policy_and_fake_decision_are_unchanged_by_masking`, `test_fake_cache_key_is_byte_identical_to_pre_masking_value` |
| Live adapters post the right shape, retry once, then fail loudly | `tests/unit/test_llm_live.py` (fake opener and fake SDK clients; `test_retries_once_with_parse_error_appended`, `test_raises_llm_error_after_two_bad_answers`) |
| Shipped backend configs carry variable names, never secrets | `test_shipped_configs_have_expected_shape_and_no_secrets`, `test_vllm_requires_named_env_var` |
| Fake and live decisions never share a cache entry | `test_fake_and_live_decisions_never_share_cache_entries` |
| No MCP tool result contains a raw sample counterparty or reference | `tests/unit/test_mcp_review_server.py::test_no_tool_result_contains_raw_counterparty_or_reference` (10 strings from `data/samples/acme_*.csv`) |
| The MCP server refuses to complete a run with open tasks | `test_complete_review_refuses_while_tasks_are_open` |
| Late failure leaves no partial run behind | `test_persistent_workflow_rolls_back_partial_run_on_late_failure` |
| Duplicate source files and rows are idempotent | `test_sqlite_store_is_idempotent_for_duplicate_source_files_and_rows` |
| Upstream data-quality problems are surfaced, not hidden | `test_ingestion_diagnostics_surface_client_data_quality_issues`, `test_source_diagnostics_finds_duplicate_reference` |
| Python-exported events fit the Go worker's contract | `test_normalized_events_export_matches_go_worker_contract_shape` and the Go `schema_test.go` |
| The demo's summary matches a golden shape | `tests/golden/test_expected_summary.py` against `data/golden/expected_summary.json` |
| Unsupported source shapes are rejected before a run is created | `test_reconciliation_rejects_unsupported_source_shapes_before_run_creation` |

## Honest limits

Three live backends ship and none has been run by the harness: the adapters are exercised against fake
transports, so their accuracy, latency and cost are pending, and the results card says so. The review gate
finalises a run once every task is resolved; it does not send the human's answers back to the model or
re-adjudicate anything. Matching is pairwise within bounded candidate windows; one-to-many and many-to-many
matching are not implemented. Sample data is synthetic and the golden replay scores one client pair. The
streaming profile validates the boundary, not throughput. The masking policy is a static rule set with a
version tag, not a classifier; it redacts the fields it names and nothing else.

## Where it sits among the other projects

LedgerLens is the engine that [HARBORMASTER](https://github.com/roshanrana/Harbormaster) feeds: Harbormaster
decides which files, which client and which value date; LedgerLens decides which rows match.
[DRYDOCK](https://github.com/roshanrana/drydock) is the sibling that generates the ingestion pipelines whose
field mapping Harbormaster consumes, and it is where the pattern LedgerLens now uses came from: a bounded
LangGraph graph on a SQLite checkpointer, a real `interrupt()` before anything irreversible, resume validated in
the service and arriving from another process, and the same tools exposed over MCP.
[SHADOWBOOK](https://github.com/roshanrana/shadowbook) applies the same reconciliation instinct between two
ledgers rather than two files. The three-tier ladder here is the same idea as Harbormaster's mapping ladder,
applied to rows instead of columns.
