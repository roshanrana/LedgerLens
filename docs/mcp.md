# LedgerLens MCP review server

`ledgerlens-review` exposes the human review gate to any MCP client: Claude Desktop, Cursor,
Claude Code, or a script using the `mcp` SDK. A reviewer can list runs, read the review tasks
the matching engine raised, inspect a **masked** candidate pair with the machine's reasoning,
record a decision and complete the review, without ever seeing a raw counterparty or reference.

Module: `ledgerlens/mcp/server.py` (design: `docs/05-langgraph-review-gate-design.md` §4, §6).

## Starting the server

The server speaks stdio. It reads the SQLite database named by `LEDGERLENS_DB`
(default `.ledgerlens/ledgerlens.db`, relative to the working directory). Seed one first:

```
.venv/Scripts/python.exe -m ledgerlens.cli demo          # or any `reconcile` run
```

Then either entry point starts the server:

```
.venv/Scripts/python.exe -m ledgerlens.mcp.server
.venv/Scripts/python.exe -m ledgerlens.cli mcp
ledgerlens mcp                                           # the console script, same program
```

All three run the same `ledgerlens.mcp.server.main()`; the CLI subcommand imports it lazily and prints a clear
message if the `mcp` package is missing.

Set `LEDGERLENS_DB` to point somewhere else:

```
LEDGERLENS_DB=C:/data/ledgerlens.db .venv/Scripts/python.exe -m ledgerlens.mcp.server
```

### Claude Desktop

Add to `claude_desktop_config.json` (`%APPDATA%\Claude\` on Windows,
`~/Library/Application Support/Claude/` on macOS), using absolute paths:

```json
{
  "mcpServers": {
    "ledgerlens-review": {
      "command": "C:/Code-Central/LedgerLens/.venv/Scripts/python.exe",
      "args": ["-m", "ledgerlens.mcp.server"],
      "cwd": "C:/Code-Central/LedgerLens",
      "env": { "LEDGERLENS_DB": "C:/Code-Central/LedgerLens/.ledgerlens/ledgerlens.db" }
    }
  }
}
```

Restart Claude Desktop; the seven tools appear under the tools icon.

### Cursor

Add to `.cursor/mcp.json` in the workspace (or `~/.cursor/mcp.json` globally):

```json
{
  "mcpServers": {
    "ledgerlens-review": {
      "command": "C:/Code-Central/LedgerLens/.venv/Scripts/python.exe",
      "args": ["-m", "ledgerlens.mcp.server"],
      "env": { "LEDGERLENS_DB": "C:/Code-Central/LedgerLens/.ledgerlens/ledgerlens.db" }
    }
  }
}
```

### Claude Code

```
claude mcp add ledgerlens-review -e LEDGERLENS_DB=C:/Code-Central/LedgerLens/.ledgerlens/ledgerlens.db -- C:/Code-Central/LedgerLens/.venv/Scripts/python.exe -m ledgerlens.mcp.server
```

## Tools

Every tool returns a JSON object. Failures never raise across the wire; they come back as
`{"error": "..."}` (unknown ids, unsupported decisions, already-resolved tasks, blank
reviewer or notes, open tasks on completion). Every call opens and closes its own database
connection.

| Tool | Arguments | Returns |
|------|-----------|---------|
| `list_runs` | `limit=20` | `{"runs": [run, ...]}` newest first |
| `get_run` | `run_id` | `{"run", "open_review_tasks", "counts", "decisions_by_tier"}` |
| `list_review_tasks` | `run_id`, `status=None` (`open` / `resolved`) | `{"run_id", "status", "tasks": [task, ...]}` |
| `get_review_pair` | `task_id` | `{"task", "pair": masked pair, "machine_decision": {tier, decision, confidence, reason_code, explanation}}` |
| `resolve_review_task` | `task_id`, `decision`, `notes`, `reviewer` | `{"task", "decision"}`; `notes` and `reviewer` must be non-empty |
| `complete_review` | `run_id`, `reviewer`, `note=""` | completion record from the service; error while tasks are open |
| `get_report` | `run_id` | `{"run_id", "report": markdown, "counts", "decisions_by_tier"}` |

`decision` is one of `match`, `no_match`, `duplicate`, `needs_review`, `unmatched`.

### What a masked pair looks like

`get_review_pair` hands out `mask_pair(...)` from `ledgerlens/llm/masking.py` (frozen
contract). Each side keeps `id`, `date`, `amount`, `currency`, `source_system`; `reference`
and `counterparty` become stable hashed tokens (equal tokens mean equal values, so a reviewer
can still see that both sides name the same party); the description has digit runs of five or
more replaced by `#` and is capped at 80 characters. `masking_version` records the policy
applied. The raw values are never returned by any tool, including `get_report`.

## Short transcript

```
> list_runs {"limit": 5}
{"runs": [{"id": "run_61b2afc50e4a", "client_id": "acme", "status": "awaiting_review", ...}]}

> list_review_tasks {"run_id": "run_61b2afc50e4a", "status": "open"}
{"run_id": "run_61b2afc50e4a", "status": "open",
 "tasks": [{"id": "review_run_61b2afc50e4a_txn_a73c…_txn_8510…", "candidate_pair_id": "pair_cf69743ff28789b8",
            "priority": "medium", "status": "open", "reason": "llm_low_confidence",
            "suggested_decision": "needs_review", ...}]}

> get_review_pair {"task_id": "review_run_61b2afc50e4a_txn_a73c…_txn_8510…"}
{"task": {...},
 "pair": {"pair_id": "pair_cf69743ff28789b8",
          "left":  {"id": "txn_8510a5fbf42a0ec1", "date": "2026-05-04", "amount": "-25.00", "currency": "USD",
                    "source_system": "bank", "description": "bank service fee may",
                    "reference_token": "", "counterparty_token": "aabfc736adc8", "masking_version": "ledgerlens.masking.v1"},
          "right": {"id": "txn_a73c906da54d75b7", "date": "2026-05-04", "amount": "25.00", "currency": "USD",
                    "source_system": "ledger", "description": "bank monthly service charge",
                    "reference_token": "", "counterparty_token": "", "masking_version": "ledgerlens.masking.v1"},
          "features": {..., "candidate_score": 0.6657}, "blocking_reason": "...", "masking_version": "ledgerlens.masking.v1"},
 "machine_decision": {"tier": "llm", "decision": "needs_review", "confidence": 0.72, "reason_code": "llm_low_confidence",
                      "explanation": "Amount and date align, but the evidence lacks a reliable reference. Routed to review by confidence policy."}}

> resolve_review_task {"task_id": "review_…", "decision": "no_match", "notes": "", "reviewer": "j.doe"}
{"error": "notes is required and must not be empty"}

> resolve_review_task {"task_id": "review_…", "decision": "match", "notes": "Same-day bank fee; ledger posts it as a charge.", "reviewer": "j.doe"}
{"task": {..., "status": "resolved", "reviewer_decision": "match", "assigned_to": "j.doe"},
 "decision": {"tier": "human", "decision": "match", "confidence": 1.0, "reason_code": "human_review_resolution", ...}}

> complete_review {"run_id": "run_61b2afc50e4a", "reviewer": "j.doe"}
{... run status "completed" ...}          # or {"error": "run … still has 1 open review task(s); …"} if called too early
```

## Tests

`tests/unit/test_mcp_review_server.py` seeds a temporary database with
`ledgerlens.api.resources.run_demo`, drives every tool through an in-memory `Client(server)`,
asserts that no counterparty or reference string from `data/samples/acme_*.csv` appears in any
tool result, and spawns `python -m ledgerlens.mcp.server` over stdio once.

```
.venv/Scripts/python.exe -m unittest tests.unit.test_mcp_review_server -v
```
