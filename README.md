# LedgerLens

LedgerLens is a portfolio-ready, AI-assisted reconciliation agent. It is built to show forward deployed engineering judgment: deterministic matching first, fuzzy matching for messy cases, an offline fake LLM adjudicator for ambiguous pairs, human review for risk, and audit-ready reporting.

## What It Demonstrates

- Python reconciliation core with SQLite persistence.
- Config-driven source onboarding for messy client files.
- Tiered matching: exact, deterministic rules, fuzzy scoring, and fake LLM adjudication.
- LLM cost controls through persistent pair caching.
- Human-in-the-loop review tasks.
- Markdown reconciliation reports with source diagnostics and unmatched exceptions.
- Atomic persisted runs that roll back cleanly on late failures.
- Normalized event export for sidecar replay and streaming demos.
- Kafka/Redpanda-ready event contracts.
- Go match-worker source for event transformation and candidate generation.
- Offline default tests; no OpenAI key is required.

For the portfolio narrative, see `docs/04-functionality-real-world-ai-fde-brief.md`.

## Quick Start

Use the bundled Python path in this Codex workspace if `python` is not on PATH:

```powershell
& "C:\Users\rosha\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m ledgerlens.cli --db .ledgerlens\ledgerlens.db demo
```

Generic command when Python is on PATH:

```bash
python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db demo
```

Run custom source/profile pairs:

```bash
python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db reconcile \
  --client-id acme \
  --source data/samples/acme_bank_statement.csv configs/clients/acme_bank.json \
  --source data/samples/acme_ledger_export.csv configs/clients/acme_ledger.json
```

## Tests

The default test suite is deterministic and offline:

```bash
python -m unittest discover -s tests
```

Run the full local verifier, including Docker-backed Go checks when Docker is available:

```bash
python scripts/verify.py
```

Require Docker-backed checks explicitly:

```bash
python scripts/verify.py --docker required
```

The verifier runs Python tests, a CLI demo smoke, Go worker tests, a worker container build, a containerized file-mode smoke, and Redpanda compose validation.
The container smoke uses normalized events exported from a real Python reconciliation run.

Run the optional Redpanda round-trip smoke:

```bash
python scripts/verify.py --docker required --kafka-smoke
```

## Local API

Run the dependency-free JSON API:

```bash
python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db serve --port 8080
```

Useful endpoints:

- `POST /demo`
- `POST /runs`
- `GET /runs/<run_id>/events/normalized`
- `GET /review/tasks?run_id=<run_id>&status=open`
- `POST /review/tasks/<task_id>/resolve`
- `GET /runs/<run_id>/report`

## Optional Streaming Profile

Kafka-compatible local infrastructure is represented by the Redpanda profile:

```bash
docker compose --profile streaming up
```

The Go worker source lives in `go/match-worker`. It supports file mode for cheap local demos and Kafka mode for the optional Redpanda streaming boundary. Kafka offsets are committed only after candidate events are written.

Verify the Go worker without installing Go locally:

```powershell
docker run --rm -e GOWORK=off -v "${PWD}:/repo" -w /repo/go/match-worker golang:1.23-alpine go test ./...
docker build -t ledgerlens-match-worker:test ./go/match-worker
python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db export-normalized-events <run_id> | docker run --rm -i ledgerlens-match-worker:test --mode file --input - --output -
docker compose --profile streaming config
python scripts/verify.py --docker required --kafka-smoke
```

## Live LLM Key

No live OpenAI key is required for the default project. The fake adjudicator preserves the same structured boundary a live model would use while keeping tests reliable and cost-free.
