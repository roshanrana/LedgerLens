# LedgerLens Functionality, Real-World Value, And FDE AI Narrative

Status: Portfolio brief  
Date: 2026-08-28  
Project: LedgerLens, an AI-assisted reconciliation agent

## 1. Executive Summary

LedgerLens is an AI-assisted financial reconciliation system built to demonstrate practical forward deployed engineering judgment. It ingests messy account statements from multiple client systems, normalizes the data into a canonical transaction model, reconciles transactions through a cost-aware matching pipeline, escalates ambiguous cases to an LLM-style adjudication boundary, routes risky items to human review, and produces audit-ready reports.

The project is intentionally not "LLM everywhere." It shows the engineering discipline expected from an FDE: use deterministic logic where it is cheaper and more reliable, use AI only where ambiguity creates value, preserve human control, and make every integration traceable.

Core positioning:

> LedgerLens reconciles cheaply first, reasons expensively last, and explains every decision.

## 2. Real-World Problem

Financial reconciliation is a recurring operational problem across banks, fintechs, enterprises, treasury teams, and accounting operations. Teams routinely compare bank statements, ledger exports, payment processor files, lockbox reports, and internal account movements. These files rarely arrive in a clean, uniform shape.

Common real-world issues LedgerLens is designed to address:

- Different source schemas for the same business event.
- Debit and credit sign convention differences.
- Posting date delays between bank and ledger systems.
- Missing or inconsistent references.
- Slightly different descriptions for the same transaction.
- Duplicate transaction IDs or duplicate source rows.
- Ambiguous records that are risky to auto-match.
- Need for analyst review, notes, and audit evidence.
- Pressure to reduce close-cycle manual work without creating false positives.

The system models the way real reconciliation teams work: automate obvious cases, explain gray areas, and keep an auditable human review path for the exceptions.

## 3. End-To-End Functionality

LedgerLens currently provides a full local reconciliation workflow:

1. Start a reconciliation run.
2. Ingest two client source files.
3. Load source-specific mapping profiles.
4. Preserve raw rows and source provenance.
5. Normalize each row into canonical transaction fields.
6. Generate source diagnostics.
7. Create bounded candidate pairs.
8. Apply exact matching.
9. Apply deterministic rule matching.
10. Score fuzzy candidates.
11. Escalate ambiguous candidates through a fake LLM adjudication contract.
12. Cache LLM adjudication results.
13. Route low-confidence cases to human review.
14. Resolve review tasks through CLI or API.
15. Detect transactions without matched or reviewable counterparts.
16. Persist decisions, metrics, and audit events.
17. Generate Markdown reports.
18. Export normalized events for Go/Kafka sidecar replay.

The default project is deterministic and offline. No OpenAI key is required to run the tests or demo.

## 4. Feature Catalog

### 4.1 Config-Driven Source Onboarding

Mapping profiles in `configs/clients/` define how messy client files are interpreted:

- Client ID.
- Source system.
- Account ID.
- File type.
- Default currency.
- Debit/credit strategy.
- Source column mappings.
- Date formats.
- Required fields.
- Reference extraction patterns.
- Description stopwords.

Why it matters:

- FDEs often walk into client-specific data environments.
- The project shows that a new client source can be onboarded through configuration and focused tests, instead of hard-coding every new file layout.

### 4.2 CSV Ingestion And Raw Evidence Preservation

The ingestion layer reads source CSV files, computes file and row hashes, assigns deterministic IDs, and stores original row payloads.

Why it matters:

- Real finance systems need traceability back to the source record.
- Preserving raw payloads supports audit, debugging, replay, and dispute resolution.

### 4.3 Canonical Transaction Normalization

LedgerLens normalizes incoming records into a consistent model:

- Posting date.
- Value date.
- Amount.
- Currency.
- Direction.
- Raw and normalized description.
- Counterparty.
- Reference.
- Exact fingerprint.
- Loose fingerprint.
- Quality flags.

Why it matters:

- Most reconciliation complexity starts before matching.
- Normalization turns messy integration data into a stable contract that matching, reporting, and sidecar systems can all use.

### 4.4 Source Quality Diagnostics

The system surfaces diagnostics such as:

- Total rows.
- Normalized rows.
- Missing reference signals.
- Missing external IDs.
- Duplicate external IDs.
- Parse errors.
- Quality flag counts.

Why it matters:

- A strong FDE does not only make downstream matching smarter.
- They also identify upstream data quality problems that cause operational pain.

### 4.5 Tiered Matching Pipeline

LedgerLens uses multiple matching tiers:

- Exact fingerprint matching for obvious cases.
- Deterministic rule matching for known finance patterns.
- Fuzzy scoring for messy descriptions and date gaps.
- Fake LLM adjudication for ambiguous pairs.
- Human review for low-confidence outcomes.

Why it matters:

- This demonstrates cost-aware AI system design.
- Most transactions should not need an LLM.
- The LLM boundary is reserved for cases where semantic reasoning may actually help.

### 4.6 Candidate Blocking

Before expensive matching, LedgerLens generates bounded candidate pairs using:

- Same currency.
- Amount tolerance.
- Date window.
- Shared references.
- Loose fingerprints.
- Similar descriptions or counterparties.

Why it matters:

- Candidate blocking avoids uncontrolled pairwise matching growth.
- It is the difference between a toy reconciliation script and a system that can plausibly scale.

### 4.7 LLM-Style Adjudication Boundary

The project includes a deterministic fake LLM adjudicator with the same structured boundary a live model integration would use:

- Compact pair input.
- Computed features.
- Policy thresholds.
- Structured decision output.
- Confidence.
- Reason code.
- Explanation.

Why it matters:

- Tests stay reliable and cost-free.
- The architecture still demonstrates where and how a real LLM would be integrated.
- The design avoids passing entire files or uncontrolled context into a model.

### 4.8 LLM Cache And Cost Controls

LedgerLens caches adjudication outcomes by a normalized cache key. Reports include LLM call and cache metrics.

Why it matters:

- Agentic finance systems need cost controls.
- Repeated ambiguous pairs should not trigger repeated model calls.
- This creates a clear interview talking point around token, latency, and budget discipline.

### 4.9 Human-In-The-Loop Review

Ambiguous or low-confidence outcomes become review tasks. A reviewer can resolve a task through the CLI or API, and the system records a human-tier match decision.

Implemented review controls:

- Open review task listing.
- Review resolution.
- Reviewer notes.
- Reviewer identity.
- Conflict response for already-resolved tasks.
- Audit event for review resolution.

Why it matters:

- Real reconciliation systems cannot silently automate every gray area.
- Human authority, reviewer notes, and immutable decision history are crucial for trust.

### 4.10 Unmatched Exception Reporting

LedgerLens identifies transactions that have no matched or reviewable counterpart and reports unmatched counts by side.

Why it matters:

- Reconciliation is not only about finding matches.
- The most important operational items are often the records that did not reconcile.

### 4.11 SQLite Persistence With Atomic Runs

The local database stores:

- Reconciliation runs.
- Source files.
- Raw transactions.
- Normalized transactions.
- Candidate pairs.
- Match decisions.
- Review tasks.
- LLM cache entries.
- Audit events.
- Run metrics.

Persistent reconciliation runs are wrapped in a transaction. A late failure rolls back the full run instead of leaving half-written state.

Why it matters:

- Finance workflows need consistency.
- SQLite keeps the portfolio demo portable, while the schema maps cleanly to a production Postgres design.

### 4.12 Audit-Ready Reporting

Reports summarize:

- Source files.
- Normalized transaction count.
- Candidate pair count.
- Match decision count.
- Open review task count.
- Unmatched transaction count.
- LLM calls and cache hits.
- Decisions by tier.
- Source diagnostics.
- Audit event summary.

Why it matters:

- The output is useful to controllers, reconciliation analysts, auditors, and implementation teams.
- It demonstrates that the system explains decisions instead of only producing a match/no-match result.

### 4.13 Dependency-Free JSON API

The API exposes:

- `POST /demo`
- `POST /runs`
- `GET /runs/<run_id>/events/normalized`
- `GET /review/tasks?run_id=<run_id>&status=open`
- `POST /review/tasks/<task_id>/resolve`
- `GET /runs/<run_id>/report`

Why it matters:

- This gives the project an integration surface without adding a heavy web framework.
- It demonstrates how the core workflow can be embedded into other systems or a future UI.

### 4.14 CLI Workflow

The CLI supports:

- Database initialization.
- Bundled demo runs.
- Custom source/profile reconciliation.
- Report generation.
- Review task listing.
- Review task resolution.
- Normalized event export.
- Local API serving.

Why it matters:

- FDEs often need practical command-line tools for client demos, data validation, and rapid troubleshooting.

### 4.15 Go Match Worker

The Go sidecar consumes normalized transaction events and emits bounded candidate-created events.

Supported modes:

- File mode for local replay.
- Kafka mode for event-driven integration.

Reliability features:

- Idempotency by input event and emitted pair.
- Runtime validation of normalized transaction event fields.
- Manual Kafka offset commits after successful candidate writes.
- Non-root Docker image.

Why it matters:

- Go is used where it is justified: high-throughput deterministic worker logic and Kafka integration.
- The project demonstrates Go without splitting every function into a separate service.

### 4.16 Kafka/Redpanda Event Boundary

The project defines event schemas and fixtures under `contracts/` for:

- Statement ingested.
- Transaction normalized.
- Match candidate created.
- Match decision created.
- Review required.
- Review resolved.
- Report generated.

Why it matters:

- This models a credible enterprise integration boundary.
- The Python workflow can export normalized events.
- The Go worker can consume those events in file mode or through Kafka.
- The optional Redpanda smoke proves a real produce/consume round trip.

### 4.17 Verification And CI

The project includes a local verifier:

```bash
python scripts/verify.py
```

Docker-backed verification:

```bash
python scripts/verify.py --docker required
```

Optional real Kafka smoke:

```bash
python scripts/verify.py --docker required --kafka-smoke
```

Verification covers:

- Python unit, contract, golden, and e2e tests.
- CLI demo smoke.
- Dockerized Go tests.
- Go worker Docker build.
- Python-exported normalized events piped into the Go worker.
- Docker Compose Redpanda configuration.
- Optional real Redpanda round trip.

Why it matters:

- A portfolio project is stronger when a reviewer can prove it quickly.
- The verifier makes the demo reproducible across machines.

## 5. How LedgerLens Solves Real-World Reconciliation Problems

### Problem: Client Files Are Messy

LedgerLens uses mapping profiles and normalization rules instead of assuming one perfect schema.

Real-world value:

- Faster onboarding.
- Less custom code per client.
- Clearer implementation handoff.

### Problem: Rule-Based Matching Is Too Brittle

LedgerLens combines exact, rule, fuzzy, and AI-assisted tiers.

Real-world value:

- High-confidence cases remain deterministic.
- Messy but plausible matches get a richer evaluation.
- Ambiguous cases are escalated instead of guessed.

### Problem: AI Can Be Expensive And Risky

LedgerLens only sends ambiguous candidates to the LLM boundary and caches results.

Real-world value:

- Lower cost.
- Lower latency.
- Smaller prompts.
- Better auditability.
- Reduced risk of model overreach.

### Problem: Analysts Need Trustworthy Exceptions

LedgerLens creates review tasks and records human resolutions with notes and audit events.

Real-world value:

- Human judgment remains part of the control framework.
- Analysts spend time on the exceptions that matter.
- Review outcomes are inspectable later.

### Problem: Engineering Teams Need Integration Paths

LedgerLens exposes a CLI, JSON API, event contracts, and a Go/Kafka sidecar.

Real-world value:

- Easy local demo.
- Simple automation surface.
- Clear enterprise event-driven migration path.
- Language choices map to actual system responsibilities.

### Problem: Auditors Need Evidence

LedgerLens stores source provenance, raw rows, decisions, review resolutions, metrics, and audit events.

Real-world value:

- Decisions are explainable.
- Data lineage is preserved.
- Reports can support finance and compliance review.

## 6. How The Project Demonstrates AI Use

LedgerLens demonstrates AI in two complementary ways:

1. AI inside the product.
2. AI as part of the design, development, QA, and integration process.

### 6.1 AI Inside The Product

The product uses an AI-style adjudication tier for ambiguous reconciliation pairs.

Important design choices:

- The model receives compact structured facts, not entire files.
- Deterministic tiers run before the LLM tier.
- The LLM response shape is explicit and testable.
- Low-confidence outputs route to review.
- Results are cached.
- The fake LLM keeps the project runnable without credentials.

This is the core AI systems design lesson: AI is most valuable when it is bounded by workflow, evidence, cost controls, and human oversight.

### 6.2 AI For Market And Product Design

AI was used to shape the product strategy around:

- Finance automation trends.
- Task-specific agent patterns.
- FDE hiring signals.
- Practical use of Go and Kafka.
- Cost-aware LLM escalation.
- Human-in-the-loop controls.
- Demo scope discipline.

The result was a high-level design document before implementation began, which helped avoid building random features without a coherent story.

### 6.3 AI For Low-Level Architecture

AI was used to break the system into buildable components:

- Domain model.
- Ingestion and normalization.
- Matching engine.
- LLM adjudication and cache.
- Persistence.
- Reporting.
- API and CLI.
- Go/Kafka sidecar.
- Contract tests.
- End-to-end verification.

This produced a low-level multi-agent design document with explicit module ownership and test expectations.

### 6.4 AI For Test-Driven Development

The project was built using a TDD-oriented approach:

- Define expected behavior first.
- Add focused unit and e2e tests.
- Implement the smallest working slice.
- Run regression checks frequently.
- Expand tests around discovered defects.

Examples of defects caught and fixed through AI-assisted QA:

- Same-database reruns initially risked audit ID collisions.
- Source-file idempotency needed to be run-scoped.
- Custom source flows needed stricter validation.
- Review resolution needed conflict handling.
- Persistent reconciliation needed transaction boundaries.
- Kafka offsets needed manual commit semantics.
- Redpanda health checks needed reliable parsing.

### 6.5 AI For Multi-Agent QA

Specialized AI QA agents reviewed the project from different angles:

- Python/API/reconciliation correctness.
- Go/Kafka/event-boundary reliability.

That surfaced portfolio-relevant issues that were then fixed and regression-tested. This mirrors how an FDE can use AI not only to write code, but to create parallel review pressure across product, backend, integration, and reliability concerns.

### 6.6 AI For Integration Verification

AI helped connect the Python and Go parts through a real contract:

- Python exports normalized transaction events as NDJSON.
- Go consumes those events in file mode.
- Redpanda smoke produces those events to Kafka.
- The Go worker emits candidate-created events.
- The smoke consumes and validates a candidate event.

This is useful because AI-generated code is only valuable when it survives integration. LedgerLens demonstrates that principle directly.

## 7. Why This Is Useful For A Forward Deployed Engineer Role

Forward deployed engineers sit between customers, product, data, and production systems. LedgerLens maps well to that role because it demonstrates:

- Ability to understand a real operational workflow.
- Ability to handle messy customer data.
- Ability to design configurable onboarding instead of one-off scripts.
- Ability to combine deterministic systems with bounded AI.
- Ability to use Go and Kafka where they make architectural sense.
- Ability to build auditability into product behavior.
- Ability to preserve human review for high-risk decisions.
- Ability to test and verify across languages and runtime boundaries.
- Ability to create a demo that a non-engineering stakeholder can understand.
- Ability to explain tradeoffs around cost, latency, reliability, and trust.

The project is especially strong for FDE interviews because it can be discussed at multiple levels:

- Business problem: close-cycle reconciliation and exception reduction.
- Product behavior: tiered matching, review queue, reports.
- Data engineering: ingestion, normalization, diagnostics, contracts.
- AI engineering: structured prompts, LLM cache, confidence routing.
- Backend engineering: SQLite schema, atomic runs, API, CLI.
- Systems engineering: Go worker, Docker, Kafka, Redpanda.
- Delivery discipline: design docs, tests, verifier, runbook.

## 8. Suggested Interview Narrative

Short version:

> LedgerLens is a reconciliation agent that demonstrates how I would deploy AI into a real finance workflow. It starts with messy bank and ledger files, normalizes them into an auditable model, runs deterministic matching first, escalates only ambiguous pairs to an LLM-style adjudicator, routes risky cases to human review, and exports events to a Go/Kafka sidecar for enterprise integration.

Deeper version:

> The main design decision was not to use an LLM for everything. Reconciliation has many cases where exact fingerprints and deterministic rules are faster, cheaper, and more auditable. The AI tier is reserved for ambiguous pairs, and even there it uses compact structured inputs, confidence thresholds, caching, and human review. That makes the system practical rather than flashy.

Go/Kafka version:

> I kept Go focused on the sidecar workload where it is credible: consuming normalized transaction events, generating bounded candidate events, and committing Kafka offsets only after candidate writes succeed. The Python workflow remains the orchestration and reporting layer. That split shows I can use distributed systems without overcomplicating the core product.

FDE version:

> The project is designed around client onboarding. A new source is mostly a mapping profile plus tests. The system surfaces source quality diagnostics, preserves raw evidence, exports events for replay, and creates reports that finance stakeholders can read. That is the kind of practical implementation path I would want in a customer deployment.

## 9. How To Demo The Project

Run the local demo:

```bash
python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db demo
```

Run custom source/profile reconciliation:

```bash
python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db reconcile \
  --client-id acme \
  --source data/samples/acme_bank_statement.csv configs/clients/acme_bank.json \
  --source data/samples/acme_ledger_export.csv configs/clients/acme_ledger.json
```

Start the local API:

```bash
python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db serve --port 8080
```

Run full verification:

```bash
python scripts/verify.py --docker required
```

Run the real Kafka smoke:

```bash
python scripts/verify.py --docker required --kafka-smoke
```

## 10. Current Verification Status

As of this brief, the full local verification path has passed with:

- 34 Python tests.
- CLI demo smoke.
- Dockerized Go tests.
- Go worker Docker build.
- Python event export into the Go worker.
- Docker Compose streaming validation.
- Optional Redpanda Kafka produce/consume smoke.

This gives the project a credible story: it is not only designed well, it is executable and verifiable.

## 11. Future Extensions

Strong next steps, if the project is expanded:

- Add a small review UI.
- Add production Postgres support.
- Add live OpenAI adjudication behind an explicit environment flag.
- Add richer unmatched aging and exception owner workflows.
- Add source-quality recommendations from historical review outcomes.
- Add metrics export for Prometheus or OpenTelemetry.
- Add support for more file types such as XLSX.
- Add batch replay commands from persisted event exports.

These are intentionally future-facing. The current build already demonstrates the core FDE signal: practical AI integration, messy data handling, deterministic-first engineering, human review, auditability, Go/Kafka integration, and reproducible delivery.
