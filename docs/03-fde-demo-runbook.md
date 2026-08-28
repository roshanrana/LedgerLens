# LedgerLens FDE Demo Runbook

Status: Portfolio demo guide  
Date: 2026-08-28

## Demo Story

LedgerLens shows a pragmatic forward deployed engineering pattern:

1. Start with messy client-controlled files.
2. Configure source mappings without code changes.
3. Normalize transactions into an auditable canonical model.
4. Reconcile cheaply first with exact and rule tiers.
5. Escalate ambiguous pairs to a bounded fake LLM contract.
6. Preserve human authority through review resolution.
7. Report match tiers, exceptions, cache behavior, and audit events.

The key line:

> LedgerLens reconciles cheaply first, reasons expensively last, and explains every decision.

## One-Minute Local Demo

Run the bundled reconciliation:

```powershell
& "C:\Users\rosha\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m ledgerlens.cli --db .ledgerlens\demo.db demo
```

Expected signal in the report:

- `exact` tier decisions.
- `rule` tier decisions.
- `llm` tier decision.
- One open review task.
- Unmatched transaction count.
- LLM call/cache metrics.
- Audit event summary.

## Full Verification

Run the whole local verification story:

```powershell
& "C:\Users\rosha\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\verify.py --docker required
```

This proves the Python workflow, CLI smoke path, Go worker tests, worker container build, containerized worker file-mode smoke, and Redpanda compose configuration.
The sidecar smoke consumes normalized events exported from a real LedgerLens run, so the Python and Go paths are tied together through the same contract.

For a real Redpanda round trip:

```powershell
& "C:\Users\rosha\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\verify.py --docker required --kafka-smoke
```

The Kafka smoke starts an isolated compose project, creates topics, produces Python-exported normalized events, consumes one candidate event, and tears the stack down.

## Human Review Demo

List open review tasks:

```powershell
& "C:\Users\rosha\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m ledgerlens.cli --db .ledgerlens\demo.db review-list --run-id <run_id>
```

Resolve an exception:

```powershell
& "C:\Users\rosha\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m ledgerlens.cli --db .ledgerlens\demo.db review-resolve <task_id> --decision no_match --notes "Analyst confirmed this is not the same business event." --reviewer demo-analyst
```

Reprint the report:

```powershell
& "C:\Users\rosha\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m ledgerlens.cli --db .ledgerlens\demo.db report <run_id>
```

Expected follow-up signal:

- Open review tasks drops to `0`.
- A `human:no_match` decision appears.
- A `review.resolved` audit event appears.

## New Client Source Demo

Run reconciliation against explicit source/profile pairs:

```powershell
& "C:\Users\rosha\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m ledgerlens.cli --db .ledgerlens\custom.db reconcile --client-id acme --source data\samples\acme_bank_statement.csv configs\clients\acme_bank.json --source data\samples\acme_ledger_export.csv configs\clients\acme_ledger.json
```

This is the FDE onboarding hook: a new client source should require a mapping profile and focused tests, not changes to reconciliation code.

## API Demo

Start the local JSON API:

```powershell
& "C:\Users\rosha\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m ledgerlens.cli --db .ledgerlens\api-demo.db serve --port 8080
```

Useful calls:

```bash
curl -X POST http://127.0.0.1:8080/demo -H "content-type: application/json" -d '{"client_id":"acme"}'
curl -X POST http://127.0.0.1:8080/runs -H "content-type: application/json" -d '{"client_id":"acme","sources":[{"csv_path":"data/samples/acme_bank_statement.csv","profile_path":"configs/clients/acme_bank.json"},{"csv_path":"data/samples/acme_ledger_export.csv","profile_path":"configs/clients/acme_ledger.json"}]}'
curl "http://127.0.0.1:8080/runs/<run_id>/events/normalized"
curl "http://127.0.0.1:8080/review/tasks?run_id=<run_id>&status=open"
curl -X POST http://127.0.0.1:8080/review/tasks/<task_id>/resolve -H "content-type: application/json" -d '{"decision":"no_match","notes":"Resolved by analyst","reviewer":"api-demo"}'
curl "http://127.0.0.1:8080/runs/<run_id>/report"
```

## Go/Kafka Demo

Verify the Go worker through Docker:

```powershell
docker run --rm -e GOWORK=off -v "${PWD}:/repo" -w /repo/go/match-worker golang:1.23-alpine go test ./...
docker build -t ledgerlens-match-worker:test ./go/match-worker
& "C:\Users\rosha\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m ledgerlens.cli --db .ledgerlens\demo.db export-normalized-events <run_id> | docker run --rm -i ledgerlens-match-worker:test --mode file --input - --output -
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

## Interview Talking Points

- The architecture is a modular monolith with an optional event-driven sidecar path.
- SQLite keeps the demo portable, while the schema maps cleanly to Postgres.
- Kafka is reserved for the enterprise streaming boundary.
- The fake LLM keeps tests deterministic while preserving the live model contract.
- Human review creates an explicit `human` tier decision, so analyst authority is auditable.
- Candidate blocking avoids O(n squared) matching growth and reduces LLM spend.
- Persistent reconciliation runs are transactional, so failed runs do not leave half-written audit state.
- Normalized event export connects the Python workflow to the Go/Kafka sidecar through an explicit contract.
