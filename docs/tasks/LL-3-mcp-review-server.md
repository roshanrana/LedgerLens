# LL-3 — MCP review server

**Depends on:** LL-0; integrates with LL-1's `complete_review` when it lands · **Status:** in_progress

## Goal
Any MCP client (Claude Desktop, Cursor, a script) can list runs, read review tasks, inspect a
**masked** candidate pair, resolve a task and complete the review. The server never returns a
raw counterparty, reference or unmasked description, and it cannot complete a run with open
tasks.

## Read first
- `docs/05-langgraph-review-gate-design.md` §4, §6 (frozen)
- `ledgerlens/llm/masking.py`, `ledgerlens/persistence/store.py` (`get_run`, `list_runs`, `list_review_tasks`, `resolve_review_task`, `open_review_task_count`, `get_candidate_pair`, `list_match_decisions`), `ledgerlens/api/resources.py`
- `C:\Code-Central\drydock\drydock\mcp\server.py` and `sources_server.py` (same author; the mcp 2.x SDK patterns: `MCPServer`, `@server.tool()`, wrap every tool body so errors return `{"error": "..."}`, `Client(server)` in-memory tests, `result.structured_content`, `server.run("stdio")`).

## Scope (only these files)
- `ledgerlens/mcp/__init__.py`, `ledgerlens/mcp/server.py` (new)
- `tests/unit/test_mcp_review_server.py` (new)
- `docs/mcp.md` (new: how to register `ledgerlens mcp` / `python -m ledgerlens.mcp.server` in Claude Desktop and Cursor, the tool table, a short transcript)
- Do NOT touch `ledgerlens/agents/`, `ledgerlens/api/`, `ledgerlens/cli.py`, `ledgerlens/persistence/`, `ledgerlens/llm/`.

## Acceptance criteria
1. `build_server(db_path) -> MCPServer` named `ledgerlens-review` with the seven tools in design §6; docstrings an LLM would understand; every tool opens its own `SQLiteStore(db_path)` and closes it; errors (unknown ids, bad decisions, closed tasks) return `{"error": "..."}`.
2. `get_review_pair(task_id)` returns `mask_pair(store.get_candidate_pair(task.candidate_pair_id))` plus the machine decision for that pair from `list_match_decisions` (tier, decision, confidence, reason_code, explanation) and the task itself. Test asserts the raw counterparty and reference strings from the sample CSVs (e.g. read them from `data/samples/*.csv`) appear nowhere in the JSON of any tool result.
3. `resolve_review_task` requires non-empty `reviewer` and `notes` (error dict otherwise) and delegates to `store.resolve_review_task`.
4. `complete_review(run_id, reviewer, note="")` imports `ledgerlens.api.resources.complete_review` lazily and calls it; if the function does not exist yet (LL-1 in flight) return `{"error": "review completion not available"}`; while tasks are open it must return an error dict (assert by calling on a run with an open task; if LL-1 has landed, assert the service refused; otherwise assert your own precheck refused).
5. `main()` runs stdio with `LEDGERLENS_DB` env var (default `.ledgerlens/ledgerlens.db`); `python -m ledgerlens.mcp.server` works.
6. Tests seed a temp DB by running `ledgerlens.api.resources.run_demo(db_path)` (works today: it creates review tasks), then exercise every tool over an in-memory `Client`. Include one stdio smoke test spawning `sys.executable -m ledgerlens.mcp.server` with `LEDGERLENS_DB` set, calling `list_runs`.
7. unittest (this repo does not use pytest): use `unittest.IsolatedAsyncioTestCase` for the async client calls. `.venv/Scripts/python.exe -m unittest tests.unit.test_mcp_review_server -v` green and the whole suite green.

## Validation
```
.venv/Scripts/python.exe -m unittest tests.unit.test_mcp_review_server -v
.venv/Scripts/python.exe -m unittest discover -s tests
```

## Handoff notes (≤10 lines)
