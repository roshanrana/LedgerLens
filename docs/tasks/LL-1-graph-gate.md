# LL-1 — LangGraph orchestration, review gate, CLI and API

**Depends on:** LL-0 (design doc 05, store additions, masking) · **Status:** done

## Goal
Replace the node loop in `ledgerlens/agents/workflow.py` with a compiled LangGraph
`StateGraph` on a SQLite checkpointer, add the `await_review` interrupt and `finalize_run`
node, and expose the gate through the CLI and the JSON API. Every existing test must still
pass, and the golden replay numbers must not move.

## Read first
- `docs/05-langgraph-review-gate-design.md` §2, §3, §7 (frozen)
- `ledgerlens/agents/workflow.py` (all), `ledgerlens/persistence/store.py` (the new methods near `get_run`, `transaction()`), `ledgerlens/api/resources.py`, `ledgerlens/api/server.py`, `ledgerlens/cli.py`
- `tests/unit/test_agents_workflow.py`, `tests/unit/test_persistence.py` (the rollback test), `tests/golden/test_expected_summary.py`, `tests/e2e/test_api_server.py`
- `C:\Code-Central\drydock\drydock\graph\service.py` and `build.py` for a working LangGraph 1.2 + SqliteSaver + interrupt/resume + `get_state_history` reference (same author, same conventions). Do not copy DRYDOCK's Pydantic state; here the state is a TypedDict per design §2.

## Scope (only these files)
- `ledgerlens/agents/graph.py` (new), `ledgerlens/agents/workflow.py`, `ledgerlens/agents/__init__.py`
- `ledgerlens/api/resources.py`, `ledgerlens/api/server.py`, `ledgerlens/cli.py`
- `tests/unit/test_graph_gate.py` (new), `tests/e2e/test_cli_review_gate.py` (new), `tests/unit/test_agents_workflow.py` (update `node_names` expectation only), any existing test that legitimately changes because the run status is now `awaiting_review` at the interrupt (update minimally and say so in Handoff)
- `ledgerlens/persistence/store.py` ONLY if a method in design §3 is missing or broken; LL-2 and LL-3 do not touch it

## Acceptance criteria
1. `ReconciliationWorkflow.node_names` is the thirteen names in design §2 order; `build_graph(workflow, checkpointer)` in `agents/graph.py` wires them with the conditional gate edge.
2. Existing call forms keep working: `ReconciliationWorkflow(store, MatchingConfig(...)).run(client_id, sources)` and `.run(client_id=..., sources=...)` return `PersistentWorkflowResult` (now with a `status` field: `"awaiting_review"` or `"completed"`), `.run(left, right, run_id=...)` returns `WorkflowState` in memory mode with no interrupt.
3. `GraphState` is a TypedDict holding ids and counters only (design §2). The `WorkflowState` never enters a checkpoint; the checkpointer is `SqliteSaver` over `store.db_path` in persistent mode and `InMemorySaver` in memory mode; `thread_id = run_id`.
4. At the interrupt the run status is `awaiting_review`, review tasks and decisions are committed and visible from another connection, and the preliminary report is returned. A failure raised inside any node before the interrupt still rolls back the whole run (`test_persistent_workflow_rolls_back_partial_run_on_late_failure` stays green).
5. `resources.complete_review(db_path, run_id, *, reviewer, note="")` validates `reviewer` non-empty and `store.open_review_task_count(run_id) == 0` **before** resuming (design D-4), raises `ValueError` otherwise (API maps to 409), then resumes the graph with `Command(resume={"reviewer", "note"})`; `finalize_run` appends a `run.finalized` audit event, regenerates the report so the human decision appears, sets status `completed`. Works from a *fresh* `ReconciliationWorkflow` instance and a fresh store on the same DB path (cross-process).
6. `resources.graph_history(db_path, run_id)` returns `[{"step", "node", "stage", "checkpoint_id", "created_at"}]` oldest first from `get_state_history`; `resources.get_run(db_path, run_id)` returns the store record plus `open_review_tasks`.
7. CLI: `review-complete RUN_ID --reviewer NAME [--note]`, `graph-history RUN_ID`, `run-status RUN_ID`, `mcp` (body: `from ledgerlens.mcp.server import main; main()` lazily; print a clear message if the module is absent), `--llm NAME` option on `demo` and `reconcile` (default `fake`; build the adjudicator via `ledgerlens.llm.build_adjudicator(name, StoreLLMCache(store))`, imported lazily; if LL-2 has not landed yet, fall back to the fake and note it). `demo` output ends with `Run ID: ...` and a line `Status: awaiting_review` or `Status: completed`.
8. API: `GET /runs/{id}`, `GET /runs/{id}/graph/history`, `POST /runs/{id}/review/complete` (`{"reviewer", "note"}`; 409 on open tasks or missing reviewer, 404 unknown run).
9. Tests per design §9 for graph gate and CLI e2e. Memory-mode test asserts no interrupt and `finalized` true. History test asserts ≥ 13 snapshots after completion.
10. `make check` equivalent passes locally: `.venv/Scripts/python.exe -m unittest discover -s tests`, then `.venv/Scripts/python.exe -m metrics.golden` still reports the same KPI values as `metrics/headline.json` today (6 / 6 golden checks, 75 %, 75 %, 25 %, 12 / 12). The orchestrator will extend the harness afterwards; do not edit `metrics/`.

## Validation
```
.venv/Scripts/python.exe -m unittest discover -s tests
.venv/Scripts/python.exe -m metrics.golden
.venv/Scripts/python.exe -m ledgerlens.cli --db .ledgerlens/ll1.db demo
```

## Handoff notes (≤10 lines)
- Validation: `unittest discover -s tests` -> Ran 104 tests, OK; `metrics.golden` -> golden_checks 6 / 6, match_rate 75%, straight_through_rate 75%, review_required_rate 25%, schema_conformance 12 / 12 (unchanged); `cli --db .ledgerlens/ll1.db demo` ends with `Run ID: run_...` / `Status: awaiting_review`.
- Deviation (store.py, one line): `sqlite3.connect(db_path, check_same_thread=False)`. LangGraph writes checkpoints from a pool thread, and a *second* connection cannot write while the store's run transaction holds the WAL write lock (`database is locked`, verified). So `agents/graph.py::StoreCheckpointer` is a `SqliteSaver` over `store.conn` (same `store.db_path`) that skips its per-write commit while `store.transaction()` is open: checkpoints commit with the rows at the interrupt and roll back with them on failure. Build it outside a transaction (its `setup()` would commit one).
- Harness recipe: `wf = ReconciliationWorkflow(store); r = wf.run("acme", SOURCES)` -> `r.status == "awaiting_review"`, `r.report` is the preliminary report (golden checks unchanged). Resolve: `store.resolve_review_task(task_id, decision, notes, reviewer)`. Cross-instance completion: `ReconciliationWorkflow(SQLiteStore(db_path)).complete_review(run_id, reviewer="qa", note="...")` -> `{"status": "completed", "finalized": True, "report": <final markdown with human:<decision> and run.finalized>}`; `ValueError` while tasks are open / reviewer empty / status not awaiting_review (API maps to 409, unknown run 404).
- Checkpoint count: `len(wf.graph_history(run_id))` (15 for the gated acme run: step -1 input, 0 __start__, 1-11 engine nodes, 12 await_review, 13 finalize_run) or `SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?` on the run DB. Memory mode (`run(left, right, run_id=...)`) uses `InMemorySaver`, `gated=False`, never interrupts, returns `WorkflowState` with `finalized=True`.
- `resources.run_reconciliation/run_demo` payloads gained `status` and `llm_backend`; `--llm` builds via `ledgerlens.llm.build_adjudicator(name, StoreLLMCache(store))` lazily (fake stays the workflow default and never touches LL-2). `cli mcp` imports `ledgerlens.mcp.server.main` lazily.
- Existing tests changed: only `tests/unit/test_agents_workflow.py` (node_names now 13). `persist_decisions` now writes rows itself (design §2); `generate_report` saves its own audit event; `finalize_run` appends `run.finalized` with deterministic id and sets status via `set_run_status`.
