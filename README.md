# LedgerLens

**AI-assisted reconciliation that reconciles cheaply first, reasons expensively last, and explains every decision.**

A reconciliation engine for messy client files: deterministic matching where rules are stronger, fuzzy scoring for the middle band, a language model reserved for genuinely ambiguous pairs behind a structured, cost-capped contract, human review for anything the model is not sure about, and audit-ready reports at the end. Runs offline, with a deterministic adjudicator bound by default, so every test and demo is reproducible without a key.

---

## At a glance

| | |
|---|---|
| **The problem** | Reconciliation teams compare bank statements, ledger exports and processor files that never share a schema, a sign convention or a posting date. Automating the obvious matches is easy; the cost is in the gray area, and an LLM on every pair is neither affordable nor auditable. |
| **What it does** | Config-driven source onboarding, raw-row provenance, canonical normalisation, source quality diagnostics, tiered matching, LLM adjudication with persistent pair caching, human review tasks, exception reporting, atomic runs with rollback, and event export for a Go/Kafka sidecar. |
| **Stack** | Python 3.11, SQLite, a dependency-free CLI and JSON API, JSON Schema event contracts, a Go match worker, Docker, an optional Redpanda streaming profile. |
| **Validation** | Unit, contract, golden and end-to-end tests; CLI demo smoke; Dockerised Go worker tests; worker image build; real Python-exported events replayed through the Go worker; Compose validation; optional Redpanda round trip. |

## How matching works

```
                exact fingerprint ─────────────────► matched
                        │ miss
                deterministic rules ───────────► matched        (date lag, reference variants,
                        │ miss                                   sign conventions)
                fuzzy scoring ──┬─ high ───────► matched
                                ├─ low ────────► unmatched exception
                                └─ middle band ─► LLM adjudication (cached per pair, cost-capped)
                                                         │
                                                  confident ──► matched
                                                  unsure ─────► human review task
```

Each tier only sees what the previous one declined. Adjudications are cached by pair in SQLite, so re-running a reconciliation never pays twice for the same question. The report states how many pairs the model saw, how many it did not need to, and what that saved.

## Quick start

```bash
python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db demo
```

That ingests two sample sources, reconciles them across every tier, opens review tasks for the ambiguous cases, and writes a Markdown report. To reconcile your own files, give each source a mapping profile:

```bash
python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db reconcile \
  --client-id acme \
  --source data/samples/acme_bank_statement.csv configs/clients/acme_bank.json \
  --source data/samples/acme_ledger_export.csv configs/clients/acme_ledger.json
```

Profiles in `configs/clients/` describe column mappings, date formats, debit/credit strategy, reference extraction patterns and description stopwords. Onboarding a new source is configuration plus a focused test, not code.

## Tests

The default suite is deterministic and offline:

```bash
python -m unittest discover -s tests
```

The full verifier adds the Docker-backed gates when Docker is present, and can be told to require them:

```bash
python scripts/verify.py
python scripts/verify.py --docker required
python scripts/verify.py --docker required --kafka-smoke   # optional Redpanda round trip
```

It runs the Python tests, a CLI demo smoke, the Go worker tests, a worker image build, a containerised file-mode smoke fed with events exported from a real Python run, and Compose validation.

## API

```bash
python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db serve --port 8080
```

| Endpoint | Purpose |
|---|---|
| `POST /demo` | Run the bundled demo |
| `POST /runs` | Reconcile a custom source pair |
| `GET /runs/{run_id}/report` | The Markdown report |
| `GET /runs/{run_id}/events/normalized` | Normalised events for sidecar replay |
| `GET /review/tasks?run_id=…&status=open` | Open human-review tasks |
| `POST /review/tasks/{task_id}/resolve` | Resolve a task, with an audit event |

## The Go sidecar and the streaming profile

`go/match-worker` consumes normalised-transaction events and emits candidate pairs. It runs in file mode for cheap local demos and in Kafka mode against the optional Redpanda profile:

```bash
docker compose --profile streaming up
```

Kafka offsets are committed only after candidate events are written. Event contracts live in `contracts/schemas/` as JSON Schema, with fixtures in `contracts/events/fixtures/`, and both the Python exporter and the Go consumer are tested against them. Verifying the worker needs no local Go toolchain:

```bash
docker run --rm -e GOWORK=off -v "${PWD}:/repo" -w /repo/go/match-worker golang:1.23-alpine go test ./...
docker build -t ledgerlens-match-worker:test ./go/match-worker
```

## Documentation

| | |
|---|---|
| [`docs/OVERVIEW.md`](docs/OVERVIEW.md) | The problem, the design and its reasons, what is measured |
| [`docs/SHOWCASE.md`](docs/SHOWCASE.md) | A guided tour of every feature, with the commands and files |
| [`docs/01-high-level-design.md`](docs/01-high-level-design.md) | Architecture and component boundaries |
| [`docs/02-low-level-multi-agent-design.md`](docs/02-low-level-multi-agent-design.md) | The bounded workflow, contracts and the adjudication boundary |
| [`docs/03-demo-runbook.md`](docs/03-demo-runbook.md) | Running and operating the demo |
| [`docs/04-functionality-real-world-ai-brief.md`](docs/04-functionality-real-world-ai-brief.md) | Feature catalogue and the real-world framing |

## Live model

No key is required for anything in this repository. The fake adjudicator implements the same structured contract a live model would, so swapping in a live provider changes one binding and nothing about the tests.
# LedgerLens

LedgerLens is a portfolio-ready, AI-assisted reconciliation agent. It is built to show customer-facing implementation judgment: deterministic matching first, fuzzy matching for messy cases, an offline fake LLM adjudicator for ambiguous pairs, human review for risk, and audit-ready reporting.

## Project Snapshot

| | |
|---|---|
| Delivery signal | Customer-facing AI implementation for financial operations: messy client files in, reconciled decisions, exceptions, and audit evidence out. |
| Product features | Config-driven source onboarding, raw-row provenance, canonical transaction normalization, source diagnostics, tiered matching, LLM-style adjudication cache, human review tasks, unmatched exception reporting, Markdown reports. |
| Implementation stack | Python 3.11, SQLite, dependency-free CLI/API, JSON event schemas, Go match worker, Docker, Kafka/Redpanda-compatible streaming profile. |
| Validation performed | Unit, contract, golden, and e2e tests; CLI demo smoke; Dockerized Go worker tests; worker image build; Python-exported event replay through the Go worker; Docker Compose streaming validation; optional Redpanda produce/consume smoke. |

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

For the portfolio narrative, see `docs/04-functionality-real-world-ai-brief.md`.

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
