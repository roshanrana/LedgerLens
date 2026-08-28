# LedgerLens Low-Level Multi-Agent Design

Status: Design proposal  
Date: 2026-08-24  
Project: LedgerLens

## 1. Design Intent

This document translates the high-level design into buildable slices for a multi-agent development workflow. The objective is to keep each workstream small, testable, and context-efficient.

Guiding rules:

- Build test-first.
- Prefer deterministic code before AI calls.
- Keep the default test suite offline.
- Use SQLite/direct calls for fast local development.
- Add Kafka/Go as a focused optional path, not as mandatory complexity.
- Keep each future agent's write scope disjoint.
- Keep graph state small and persist large data in SQLite.

## 2. Proposed Repository Layout

```text
.
|-- docs/
|   |-- 01-high-level-design.md
|   `-- 02-low-level-multi-agent-design.md
|-- contracts/
|   |-- events/
|   `-- schemas/
|-- configs/
|   `-- clients/
|-- data/
|   |-- samples/
|   `-- golden/
|-- ledgerlens/
|   |-- domain/
|   |-- ingestion/
|   |-- normalization/
|   |-- matching/
|   |-- agents/
|   |-- llm/
|   |-- persistence/
|   |-- reporting/
|   |-- api/
|   `-- observability/
|-- go/
|   `-- match-worker/
|       |-- cmd/
|       `-- internal/
|-- tests/
|   |-- unit/
|   |-- contract/
|   |-- golden/
|   `-- e2e/
|-- pyproject.toml
|-- go.work
|-- docker-compose.yml
`-- README.md
```

This is a target layout for implementation. No build files should be created until implementation is approved.

## 3. Canonical Domain Model

### 3.1 SourceFile

Purpose: track import provenance and idempotency.

Fields:

- `id`
- `client_id`
- `source_system`
- `account_id`
- `filename`
- `file_hash`
- `mapping_profile`
- `ingested_at`
- `row_count`
- `status`

### 3.2 RawTransaction

Purpose: preserve original evidence.

Fields:

- `id`
- `source_file_id`
- `source_row_number`
- `raw_payload_json`
- `raw_hash`
- `created_at`

### 3.3 NormalizedTransaction

Purpose: canonical transaction representation.

Fields:

- `id`
- `raw_transaction_id`
- `account_id`
- `source_system`
- `external_transaction_id`
- `posting_date`
- `value_date`
- `amount`
- `currency`
- `direction`
- `description_raw`
- `description_normalized`
- `counterparty`
- `reference`
- `fingerprint_exact`
- `fingerprint_loose`
- `quality_flags_json`
- `created_at`

### 3.4 CandidatePair

Purpose: bounded pair generated before matching.

Fields:

- `id`
- `run_id`
- `left_transaction_id`
- `right_transaction_id`
- `blocking_reason`
- `feature_vector_json`
- `candidate_score`
- `created_by`
- `created_at`

### 3.5 MatchDecision

Purpose: final or interim reconciliation decision.

Fields:

- `id`
- `run_id`
- `candidate_pair_id`
- `decision`
- `tier`
- `confidence`
- `reason_code`
- `explanation`
- `evidence_json`
- `llm_cache_key`
- `review_task_id`
- `decided_by`
- `created_at`

Allowed `decision` values:

- `match`
- `no_match`
- `duplicate`
- `needs_review`
- `unmatched`

Allowed `tier` values:

- `exact`
- `rule`
- `fuzzy`
- `llm`
- `human`

### 3.6 ReviewTask

Purpose: human-in-the-loop exception handling.

Fields:

- `id`
- `run_id`
- `candidate_pair_id`
- `priority`
- `status`
- `reason`
- `suggested_decision`
- `assigned_to`
- `reviewer_decision`
- `reviewer_notes`
- `created_at`
- `resolved_at`

### 3.7 LLMCacheEntry

Purpose: minimize repeated LLM adjudication.

Fields:

- `cache_key`
- `prompt_schema_version`
- `model`
- `input_hash`
- `output_json`
- `decision`
- `confidence`
- `reason`
- `token_estimate`
- `created_at`

### 3.8 AuditEvent

Purpose: explain every decision.

Fields:

- `id`
- `run_id`
- `entity_type`
- `entity_id`
- `event_type`
- `actor_type`
- `actor_id`
- `before_json`
- `after_json`
- `metadata_json`
- `created_at`

## 4. Matching Pipeline

### 4.1 Candidate Blocking

Goal: avoid O(n squared) pair comparisons.

Blocking strategies:

- Same currency.
- Amount within configured tolerance.
- Posting date within configured window.
- Shared reference token.
- Shared loose fingerprint.
- Similar normalized counterparty.

Expected output:

- Small list of `CandidatePair` records with compact features.

### 4.2 Exact Fingerprint Match

Input:

- Candidate pairs or blocked groups.

Exact fingerprint components:

- Normalized absolute amount.
- Currency.
- Normalized posting or value date.
- Reference if available.
- Normalized counterparty or stable description token.

Output:

- `MatchDecision(decision="match", tier="exact", confidence=1.0)`.

### 4.3 Deterministic Rule Match

Examples:

- Same amount, same reference, posting date within two business days.
- Same amount, reversed sign, same reference, across ledger and bank.
- Fee-adjusted payment where source config defines known fee pattern.
- Known transfer pattern between internal accounts.

Output:

- High-confidence match with reason code, for example `same_reference_date_window`.

### 4.4 Fuzzy Match

Feature examples:

- Amount similarity.
- Date distance.
- Reference token overlap.
- Description token similarity.
- Counterparty similarity.
- Source reliability weight.
- Historical reviewer preference if available.

Suggested scoring bands:

- `score >= 0.90`: auto-match if no high-risk flags.
- `0.65 <= score < 0.90`: ambiguous candidate, eligible for LLM adjudication.
- `score < 0.65`: no match unless a deterministic rule applies.

These thresholds should be configuration-driven and tuned through golden tests.

### 4.5 LLM Adjudication

The LLM receives only compact structured features:

```json
{
  "left": {
    "date": "2026-05-01",
    "amount": "-1250.00",
    "currency": "USD",
    "description": "ACH PAYMENT ACME INC INV 8127",
    "reference": "8127"
  },
  "right": {
    "date": "2026-05-03",
    "amount": "1250.00",
    "currency": "USD",
    "description": "ACME invoice payment 8127",
    "reference": "INV-8127"
  },
  "computed_features": {
    "amount_delta": "0.00",
    "date_delta_days": 2,
    "reference_overlap": 0.8,
    "description_similarity": 0.74
  },
  "policy": {
    "amount_tolerance": "0.00",
    "date_window_days": 3,
    "require_human_review_below_confidence": 0.85
  }
}
```

Structured output:

```json
{
  "decision": "match",
  "confidence": 0.91,
  "reason_code": "reference_and_amount_align",
  "explanation": "Amounts align exactly, references overlap, and posting dates are within policy."
}
```

Guardrails:

- No raw full-file context in prompts.
- Max one candidate pair per LLM call in V1.
- Strict JSON schema validation.
- Retry once on invalid schema.
- Route to review on low confidence or invalid repeated output.
- Store prompt hash, response hash, model, and schema version.

### 4.6 LLM Cache Key

Cache key:

```text
sha256(
  prompt_schema_version
  + model_family
  + min(left_fingerprint_loose, right_fingerprint_loose)
  + max(left_fingerprint_loose, right_fingerprint_loose)
  + feature_vector_hash
)
```

Purpose:

- Avoid duplicate LLM calls for identical normalized candidate pairs.
- Preserve reproducibility when prompt schema changes.

## 5. LangGraph Workflow

Use LangGraph as a bounded state machine.

Graph nodes:

1. `load_run_context`
2. `normalize_batch`
3. `generate_candidates`
4. `apply_exact_matches`
5. `apply_rule_matches`
6. `score_fuzzy_candidates`
7. `adjudicate_ambiguous_pairs`
8. `route_review_tasks`
9. `persist_decisions`
10. `generate_report`

State should contain IDs and counters, not large row payloads:

```json
{
  "run_id": "run_123",
  "source_file_ids": ["src_1", "src_2"],
  "candidate_pair_ids": ["pair_1", "pair_2"],
  "decision_counts": {
    "exact": 10,
    "rule": 4,
    "fuzzy": 3,
    "llm": 1,
    "human": 0
  },
  "llm_budget_remaining": 25,
  "review_task_ids": []
}
```

Human-in-the-loop:

- Use a graph interrupt only when a run requires explicit reviewer input.
- Persist the review task before interrupting.
- Resume with reviewer decision and notes.

## 6. SQLite Schema Strategy

Use SQLite for V1 with WAL enabled.

Tables:

- `reconciliation_runs`
- `source_files`
- `raw_transactions`
- `normalized_transactions`
- `candidate_pairs`
- `match_decisions`
- `review_tasks`
- `llm_cache`
- `audit_events`
- `run_metrics`

Indexes:

- `source_files(file_hash, client_id)`
- `normalized_transactions(run_id, account_id)`
- `normalized_transactions(fingerprint_exact)`
- `normalized_transactions(fingerprint_loose)`
- `candidate_pairs(run_id, left_transaction_id, right_transaction_id)`
- `match_decisions(run_id, tier, decision)`
- `review_tasks(status, priority, created_at)`
- `llm_cache(cache_key)`

Production migration note:

- SQLite is the local demo database.
- Postgres is the production migration target when multi-user review queues, concurrent writes, and hosted deployments become necessary.

## 7. Event Contracts

Kafka/Redpanda is optional for local development but included as a credible enterprise path.

Topic set:

- `ledgerlens.statement.ingested`
- `ledgerlens.transaction.normalized`
- `ledgerlens.match.candidate_created`
- `ledgerlens.match.decision_created`
- `ledgerlens.review.required`
- `ledgerlens.review.resolved`
- `ledgerlens.report.generated`

Event envelope:

```json
{
  "event_id": "evt_123",
  "event_type": "ledgerlens.transaction.normalized",
  "schema_version": "1.0",
  "occurred_at": "2026-08-24T12:00:00Z",
  "run_id": "run_123",
  "source": "ledgerlens.normalization",
  "idempotency_key": "sha256-value",
  "payload": {}
}
```

Rules:

- Events carry IDs and compact payloads.
- Source-of-truth records stay in SQLite.
- Consumers are idempotent.
- Contract tests validate JSON schemas.
- Default unit tests use an in-memory fake bus.
- Kafka integration tests run only in an explicit profile.

## 8. Go Match Worker

Purpose:

- Demonstrate Go and Kafka where they are natural.
- Consume normalized transaction events.
- Compute fingerprints or candidate blocks.
- Emit candidate-created events.

Responsibilities:

- Kafka consumer/producer.
- Idempotency by event id and transaction id.
- Concurrent candidate processing.
- Structured logs and metrics.
- Contract adherence to JSON schemas.

Non-responsibilities:

- LLM calls.
- Human review.
- Report generation.
- Business-rule sprawl that belongs in Python config.

Default fallback:

- Python in-process candidate generation remains available so local tests do not require Kafka or Go.

## 9. API And CLI Surface

CLI commands:

- `ledgerlens init-db`
- `ledgerlens ingest --client acme --profile bank-a file.csv`
- `ledgerlens reconcile --run-id run_123`
- `ledgerlens review list --run-id run_123`
- `ledgerlens review resolve --task-id task_123 --decision match`
- `ledgerlens report --run-id run_123 --format markdown`

API endpoints:

- `POST /runs`
- `GET /runs/{run_id}`
- `POST /runs/{run_id}/ingest`
- `POST /runs/{run_id}/reconcile`
- `GET /runs/{run_id}/matches`
- `GET /runs/{run_id}/exceptions`
- `GET /review/tasks`
- `POST /review/tasks/{task_id}/resolve`
- `GET /reports/{run_id}`
- `GET /metrics/{run_id}`

V1 can start CLI-first. Add API and UI after the reconciliation path is proven by tests.

## 10. TDD Plan

### 10.1 Test Pyramid

Unit tests:

- Date normalization.
- Amount sign normalization.
- Reference extraction.
- Description cleanup.
- Fingerprint generation.
- Candidate blocking.
- Deterministic rules.
- Fuzzy scoring.
- LLM cache key generation.

Contract tests:

- Event schemas.
- LLM structured output schema.
- API request/response schemas.

Golden tests:

- Messy sample statement pairs with expected matches.
- Known duplicates.
- Known non-matches.
- Fee-adjusted cases.
- Reversal cases.

Integration tests:

- SQLite persistence.
- Full local run without Kafka.
- Go worker contract using fixture events.

Optional smoke tests:

- Live LLM adjudication behind explicit environment flag.
- Redpanda/Kafka profile behind explicit test marker.

### 10.2 Build Order

1. Write canonical schemas and failing tests.
2. Implement domain models and SQLite migrations.
3. Add sample data and golden expectations.
4. Implement ingestion and normalization.
5. Implement exact and deterministic matching.
6. Implement fuzzy candidate scoring.
7. Add LLM cache and fake LLM client.
8. Add LangGraph workflow with bounded state.
9. Add reports.
10. Add Go worker and Kafka contracts.
11. Add API or lightweight UI.
12. Polish README, runbook, and demo script.

### 10.3 Default Test Commands

Target commands once implementation exists:

```bash
pytest
pytest tests/golden
go test ./...
```

Optional commands:

```bash
pytest -m llm_live
pytest -m kafka
docker compose --profile streaming up
```

## 11. Multi-Agent Development Plan

Use agents only for bounded work with disjoint write scopes. Each agent should receive:

- Relevant design section.
- Target files/directories.
- Required tests to write first.
- Explicit non-goals.
- Expected final summary.

### Agent A: Domain And Persistence

Write scope:

- `ledgerlens/domain/`
- `ledgerlens/persistence/`
- `tests/unit/test_domain_*.py`
- `tests/unit/test_persistence_*.py`

Deliverables:

- Domain dataclasses or Pydantic models.
- SQLite migrations.
- Repository methods.
- WAL setup.
- Unit tests.

Do not edit:

- Matching logic.
- LangGraph nodes.
- Go worker.

### Agent B: Ingestion And Normalization

Write scope:

- `ledgerlens/ingestion/`
- `ledgerlens/normalization/`
- `configs/clients/`
- `data/samples/`
- `tests/unit/test_ingestion_*.py`
- `tests/unit/test_normalization_*.py`

Deliverables:

- CSV ingestion.
- Mapping profile loader.
- Canonical transaction normalization.
- Source diagnostics.
- Messy sample fixtures.

Do not edit:

- LLM logic.
- Go worker.
- API.

### Agent C: Matching Engine

Write scope:

- `ledgerlens/matching/`
- `tests/unit/test_matching_*.py`
- `tests/golden/`

Deliverables:

- Fingerprint matching.
- Candidate blocking.
- Rule matching.
- Fuzzy scoring.
- Golden expected results.

Do not edit:

- Persistence migrations except through agreed repository interfaces.
- LangGraph orchestration.

### Agent D: LLM And LangGraph

Write scope:

- `ledgerlens/agents/`
- `ledgerlens/llm/`
- `tests/unit/test_agents_*.py`
- `tests/unit/test_llm_*.py`

Deliverables:

- Fake LLM client.
- LLM cache interface.
- Structured adjudication schema.
- LangGraph workflow.
- Human review interrupt design.

Do not edit:

- Matching score internals.
- Go worker.

### Agent E: Go/Kafka Worker

Write scope:

- `go/match-worker/`
- `contracts/events/`
- `tests/contract/`
- `docker-compose.yml`

Deliverables:

- Event schemas.
- Go consumer/producer skeleton.
- Candidate event generation.
- Contract tests.
- Optional Redpanda profile.

Do not edit:

- Python matching business rules, except shared event schema fixtures.

### Agent F: Reporting And Observability

Write scope:

- `ledgerlens/reporting/`
- `ledgerlens/observability/`
- `tests/unit/test_reporting_*.py`

Deliverables:

- Markdown or JSON reconciliation report.
- Run metrics.
- LLM cost and cache metrics.
- Source diagnostics summary.

Do not edit:

- Ingestion or matching internals.

### Agent G: API/CLI

Write scope:

- `ledgerlens/api/`
- CLI entrypoints.
- API tests.

Deliverables:

- CLI commands.
- FastAPI endpoints if selected.
- Thin orchestration layer over existing services.

Do not edit:

- Core domain logic.

### Agent H: QA Integration

Write scope:

- `tests/e2e/`
- `tests/golden/`
- README demo validation notes.

Deliverables:

- End-to-end test.
- Golden fixture validation.
- Demo script verification.
- Gaps and risk report.

Do not edit:

- Production implementation modules except tiny fixture adapters with approval.

## 12. Agent Coordination Rules

- Start with Domain/Persistence and Ingestion/Normalization.
- Matching can start once canonical transaction model is stable.
- LLM/LangGraph can start with fake repositories but integrates after Matching.
- Go/Kafka starts after event envelope is accepted.
- Reporting starts after MatchDecision and RunMetrics exist.
- API/CLI starts after core services exist.
- QA Integration runs continuously after the first vertical slice.

Conflict prevention:

- One agent owns one write scope.
- Shared contracts go through `contracts/`.
- Shared fixtures go through `data/golden/`.
- Agents should not modify another agent's module to "make tests pass"; they should report contract gaps.

Context control:

- Give each agent only this LLD, the HLD summary, and its target files.
- Avoid sending whole repository context after the repo grows.
- Ask agents for changed paths and verification commands only.
- Integrate one vertical slice at a time.

## 13. Cost And Token Controls During Development

API cost controls:

- Default fake LLM in tests.
- Live LLM only through explicit smoke command.
- Per-run LLM call cap in application config.
- Prompt schema versioning.
- Cache-first adjudication tests.

Build cost controls:

- Default test suite does not start Docker.
- Kafka tests are marked optional.
- Run focused tests per agent before full suite.
- Use small golden fixtures first.

Context-size controls:

- Persist rows in SQLite; pass IDs in graph state.
- Do not put entire statements into prompts.
- Reports aggregate metrics before producing narrative.
- Agent handoffs include contracts and failures, not large logs.

## 14. Acceptance Criteria For First Build Approval

The first approved build should stop when this works:

1. Ingest two sample CSV statements with different schemas.
2. Normalize them into the canonical transaction model.
3. Produce source diagnostics.
4. Run exact and deterministic matching.
5. Run fuzzy scoring on remaining candidates.
6. Use fake LLM adjudication for ambiguous pairs.
7. Cache duplicate adjudications.
8. Route low-confidence cases to review.
9. Resolve one review task manually through CLI or API.
10. Generate a report showing match tiers, exceptions, audit trail, and LLM calls avoided.

Kafka/Go acceptance for the first build:

- Event schemas exist.
- Go worker can consume a fixture normalized-transaction event and emit a candidate-created event.
- Full product still works without Kafka.

## 15. Open Decisions Before Implementation

- CLI-first or FastAPI-first for the first vertical slice.
- Whether to use Pydantic models throughout or dataclasses plus validation boundaries.
- Whether fuzzy scoring starts with RapidFuzz or a small custom scorer.
- Whether the Go worker is included in build phase 1 or phase 2.
- Whether sample data should model bank-vs-ledger, inter-account transfers, or both.

