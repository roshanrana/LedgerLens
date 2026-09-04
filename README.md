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
