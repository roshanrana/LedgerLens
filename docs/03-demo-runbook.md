# LedgerLens Demo Runbook

Status: Portfolio demo guide, updated for 0.2
Date: 2026-09-07

All commands below use the repository's virtual environment, `.venv\Scripts\python.exe` on Windows
(`.venv/bin/python` elsewhere). `python -m ledgerlens.cli` and the `ledgerlens` console script are the same
program.

## Demo Story

LedgerLens shows a pragmatic customer-facing implementation engineering pattern:

1. Start with messy client-controlled files.
2. Configure source mappings without code changes.
3. Normalize transactions into an auditable canonical model.
4. Reconcile cheaply first with exact and rule tiers.
5. Escalate ambiguous pairs to a bounded, masked adjudication contract (a deterministic fake by default).
6. Pause the run at a LangGraph interrupt until a person has resolved every review task.
7. Report match tiers, exceptions, cache behavior, human decisions and audit events.

The key line:

> LedgerLens reconciles cheaply first, reasons expensively last, and explains every decision.

## One-Minute Local Demo

Run the bundled reconciliation:

```powershell
.venv\Scripts\python.exe -m ledgerlens.cli --db .ledgerlens\demo.db demo
```

Expected signal in the preliminary report:

- `exact` tier decisions.
- `rule` tier decisions.
- `llm` tier decision.
- One open review task.
- Unmatched transaction count.
- LLM call/cache metrics.
- Audit event summary.
- The last two lines: `Run ID: run_...` and `Status: awaiting_review`.

The run is paused, not finished. Continue with the review gate below.

## Run Statuses

| Status | Meaning | Next step |
|---|---|---|
| `created` | Run row exists; the graph has not reached the gate | None while a process is running the graph; see "stuck runs" if it stays here |
| `awaiting_review` | Graph paused at `await_review`; rows, tasks and checkpoints are committed | Resolve every open task, then `review-complete` |
| `completed` | `finalize_run` ran: `run.finalized` audit event written, final report regenerated | Read the report |
| `failed` | Reserved status value; the graph rolls a failed run back rather than leaving this behind | Re-run |

A run with no review task skips the gate and goes `created -> completed` in one process.

Check a run at any time:

```powershell
.venv\Scripts\python.exe -m ledgerlens.cli --db .ledgerlens\demo.db run-status <run_id>
```

## Review Gate Demo

List open review tasks:

```powershell
.venv\Scripts\python.exe -m ledgerlens.cli --db .ledgerlens\demo.db review-list --run-id <run_id>
```

Try to complete the review too early. It is refused, exit code 1:

```powershell
.venv\Scripts\python.exe -m ledgerlens.cli --db .ledgerlens\demo.db review-complete <run_id> --reviewer demo-analyst
# Error: run <run_id> still has 1 open review task(s); resolve them first
```

Resolve the task:

```powershell
.venv\Scripts\python.exe -m ledgerlens.cli --db .ledgerlens\demo.db review-resolve <task_id> --decision no_match --notes "Analyst confirmed this is not the same business event." --reviewer demo-analyst
```

Complete the review. This resumes the graph from a fresh process, runs `finalize_run` and prints the final
report:

```powershell
.venv\Scripts\python.exe -m ledgerlens.cli --db .ledgerlens\demo.db review-complete <run_id> --reviewer demo-analyst --note "All tasks reviewed."
```

Expected follow-up signal:

- Open review tasks drops to `0`.
- A `human:no_match` decision appears under "Decisions By Tier".
- `review.resolved: 1` and `run.finalized: 1` appear under "Audit".
- The output ends with `Status: completed`; `run-status` agrees.

Show the checkpoints:

```powershell
.venv\Scripts\python.exe -m ledgerlens.cli --db .ledgerlens\demo.db graph-history <run_id>
```

Fifteen rows for the gated demo: step `-1` (input), `0` (`__start__`), `1` to `11` (the engine nodes),
`12` (`await_review`), `13` (`finalize_run`), each with its checkpoint id and timestamp.

### Cross-process resume

Every command above is its own process. The demo can run on one machine and the review can be completed
later from another shell, the JSON API or the MCP server, as long as they point at the same database file.
The resume does not need the process that paused; it needs the run id and a reviewer name. This is what
`metrics/golden.py` measures as the `review_gate` row: it pauses in one workflow instance and completes in a
second on the same database.

### When a run is stuck awaiting review

- `run-status <run_id>` shows how many tasks are still open; `review-list --run-id <run_id>` names them.
- `review-complete` says exactly why it refused: open tasks, a blank `--reviewer`, or a run that is not
  `awaiting_review` (already completed, or never gated).
- A resolved task cannot be resolved twice. If the wrong decision was recorded, note it in a fresh run; the
  audit trail is append-only.
- Completing the review needs write access to the database file. If the demo ran under another user or
  another working directory, point `--db` at the same file.
- Nothing is re-adjudicated on completion. The model is not consulted again; the human decisions stand and
  the report is regenerated around them.

## Choosing The Adjudicator

`demo` and `reconcile` take `--llm {fake,ollama,vllm,bedrock,anthropic}`; the default is `fake` and it is the
only backend the tests and the golden replay use. Each name is `configs\llm\<name>.json`:

| `--llm` | Backend | Reaches | Environment |
|---|---|---|---|
| `fake` | `fake` | nothing; deterministic | none |
| `ollama` | `openai_compat` | `http://localhost:11434/v1`, model `qwen2.5-coder:7b` | none |
| `vllm` | `openai_compat` | `http://localhost:8000/v1`, model `Qwen/Qwen2.5-Coder-7B-Instruct` | `VLLM_API_KEY` |
| `bedrock` | `bedrock` | AWS Bedrock `converse`, `anthropic.claude-opus-5`, `us-east-1` | AWS credential chain; `pip install -e ".[bedrock]"` |
| `anthropic` | `anthropic` | Anthropic API, `claude-opus-5` | `ANTHROPIC_API_KEY`; `pip install -e ".[anthropic]"` |

```powershell
.venv\Scripts\python.exe -m ledgerlens.cli --db .ledgerlens\live.db demo --llm ollama
$env:VLLM_API_KEY = "..."; .venv\Scripts\python.exe -m ledgerlens.cli --db .ledgerlens\live.db demo --llm vllm
```

The config files hold the variable name only. A missing variable or package stops the run before any
transaction is touched, with an `LLMError` naming what to set or install. Every payload sent to a live model is
masked by `ledgerlens\llm\masking.py`: references and counterparties become hashed tokens, descriptions lose
long digit runs and are truncated, and the source rows are never sent. Live decisions are cached under their
own model family and never mix with the fake's. The live backends have not been run by the harness; their
accuracy is pending.

## Full Verification

Run the whole local verification story:

```powershell
.venv\Scripts\python.exe scripts\verify.py --docker required
```

This proves the Python workflow, CLI smoke path, Go worker tests, worker container build, containerized worker
file-mode smoke, and Redpanda compose configuration. The sidecar smoke consumes normalized events exported from
a real LedgerLens run, so the Python and Go paths are tied together through the same contract.

For a real Redpanda round trip:

```powershell
.venv\Scripts\python.exe scripts\verify.py --docker required --kafka-smoke
```

The Kafka smoke starts an isolated compose project, creates topics, produces Python-exported normalized events,
consumes one candidate event, and tears the stack down.

The offline gate, where `make` is available:

```bash
make check      # tests, golden replay and headline self-check, results-card drift guard
```

Without `make`, the same three steps are `python -m unittest discover -s tests`, `python -m metrics.golden`
followed by `python -m unittest tests.golden.test_headline_metrics`, and `python metrics/render.py --check`.

## New Client Source Demo

Run reconciliation against explicit source/profile pairs:

```powershell
.venv\Scripts\python.exe -m ledgerlens.cli --db .ledgerlens\custom.db reconcile --client-id acme --source data\samples\acme_bank_statement.csv configs\clients\acme_bank.json --source data\samples\acme_ledger_export.csv configs\clients\acme_ledger.json
```

This is the implementation onboarding hook: a new client source should require a mapping profile and focused
tests, not changes to reconciliation code. `reconcile` ends with the same `Run ID` and `Status` lines as
`demo` and the same review gate applies.

## API Demo

Start the local JSON API:

```powershell
.venv\Scripts\python.exe -m ledgerlens.cli --db .ledgerlens\api-demo.db serve --port 8080
```

Useful calls, in the order a reviewer would make them:

```bash
curl -X POST http://127.0.0.1:8080/demo -H "content-type: application/json" -d '{"client_id":"acme"}'
curl -X POST http://127.0.0.1:8080/runs -H "content-type: application/json" -d '{"client_id":"acme","sources":[{"csv_path":"data/samples/acme_bank_statement.csv","profile_path":"configs/clients/acme_bank.json"},{"csv_path":"data/samples/acme_ledger_export.csv","profile_path":"configs/clients/acme_ledger.json"}]}'
curl "http://127.0.0.1:8080/runs/<run_id>"
curl "http://127.0.0.1:8080/review/tasks?run_id=<run_id>&status=open"
curl -X POST http://127.0.0.1:8080/runs/<run_id>/review/complete -H "content-type: application/json" -d '{"reviewer":"api-demo"}'
curl -X POST http://127.0.0.1:8080/review/tasks/<task_id>/resolve -H "content-type: application/json" -d '{"decision":"no_match","notes":"Resolved by analyst","reviewer":"api-demo"}'
curl -X POST http://127.0.0.1:8080/runs/<run_id>/review/complete -H "content-type: application/json" -d '{"reviewer":"api-demo","note":"All tasks reviewed"}'
curl "http://127.0.0.1:8080/runs/<run_id>/graph/history"
curl "http://127.0.0.1:8080/runs/<run_id>/report"
curl "http://127.0.0.1:8080/runs/<run_id>/events/normalized"
```

The first `review/complete` returns 409 with the reason (open tasks); the second, after the resolve, returns
the completion record. An unknown run id is 404. `POST /demo` also accepts `"llm"` with the same names as
`--llm`.

## MCP Review Server Demo

Start the server over stdio against the demo database:

```powershell
$env:LEDGERLENS_DB = ".ledgerlens\demo.db"; .venv\Scripts\python.exe -m ledgerlens.cli mcp
```

`python -m ledgerlens.mcp.server` is the same server. In practice the MCP client starts it: register the
command in Claude Desktop, Cursor or Claude Code as shown in [mcp.md](mcp.md), then ask the client to list
runs, show the open review task, inspect the pair and resolve it. The seven tools are `list_runs`, `get_run`,
`list_review_tasks`, `get_review_pair`, `resolve_review_task`, `complete_review` and `get_report`.

Talking points for the MCP demo:

- `get_review_pair` returns the masked pair and the machine decision's reason and confidence; the raw
  counterparty and reference never cross the wire, and a test asserts it against the sample files.
- `resolve_review_task` refuses a blank reviewer or blank notes.
- `complete_review` refuses while tasks are open; it is the same gate the CLI and API enforce.

## Go/Kafka Demo

Verify the Go worker through Docker:

```powershell
docker run --rm -e GOWORK=off -v "${PWD}:/repo" -w /repo/go/match-worker golang:1.23-alpine go test ./...
docker build -t ledgerlens-match-worker:test ./go/match-worker
.venv\Scripts\python.exe -m ledgerlens.cli --db .ledgerlens\demo.db export-normalized-events <run_id> | docker run --rm -i ledgerlens-match-worker:test --mode file --input - --output -
docker compose --profile streaming config
```

The worker demonstrates:

- Kafka-compatible event envelope contracts.
- Bounded candidate generation from normalized transaction events.
- Idempotent event handling.
- Manual Kafka offset commits after successful candidate writes.
- Go as a focused high-throughput worker, not unnecessary service sprawl.

## How To Onboard A New Client Source

1. Copy an existing mapping profile from `configs/clients/`.
2. Set `client_id`, `profile_name`, `source_system`, and `account_id`.
3. Map the client file columns under `column_map`.
4. Set `amount_strategy` to `signed_amount` or `debit_credit`.
5. Add date formats and reference extraction patterns.
6. Add a small sample CSV under `data/samples/`.
7. Write a focused ingestion/normalization test before changing matching logic.

## Demo Talking Points

- The architecture is a modular monolith with an optional event-driven sidecar path.
- SQLite keeps the demo portable, while the schema maps cleanly to Postgres.
- Kafka is reserved for the enterprise streaming boundary.
- The fake LLM keeps tests deterministic while preserving the live model contract; three live backends sit
  behind the same contract and are switched on by configuration, never by the presence of a key.
- Human review creates an explicit `human` tier decision, so analyst authority is auditable, and the run
  cannot be `completed` while a task is open because the graph is paused at an interrupt.
- The pause is a LangGraph checkpoint in the run database, so review can finish from another process, the
  API or an MCP client.
- Candidate blocking avoids O(n squared) matching growth and reduces LLM spend.
- Persistent reconciliation runs are transactional up to the interrupt, so failed runs do not leave
  half-written audit state or orphan checkpoints.
- Everything a model or an MCP client sees goes through one masking module with a version tag.
- Normalized event export connects the Python workflow to the Go/Kafka sidecar through an explicit contract.
