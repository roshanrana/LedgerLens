# LedgerLens Event Contracts

These contracts define the optional Kafka/Redpanda boundary for LedgerLens. SQLite remains the source of truth; events carry compact IDs, matching features, and workflow status changes so sidecars can be replayed and tested without touching the Python application internals.

## Envelope

Every event uses the same envelope:

```json
{
  "event_id": "evt_...",
  "event_type": "ledgerlens.transaction.normalized",
  "schema_version": "1.0",
  "occurred_at": "2026-08-24T19:00:00Z",
  "run_id": "run_...",
  "source": "ledgerlens.normalization",
  "idempotency_key": "sha256-or-domain-key",
  "payload": {}
}
```

Envelope rules:

- `event_id` is unique per produced event.
- `idempotency_key` is stable for the business fact represented by the event.
- Consumers must be idempotent by `event_id` and by their emitted domain IDs.
- Payloads stay compact; raw rows and full statements stay in the system of record.
- Default tests use fixtures and file-mode execution. Kafka is opt-in.

## Topics

| Topic | Producer | Consumer | Purpose |
| --- | --- | --- | --- |
| `ledgerlens.statement.ingested` | ingestion service | diagnostics, observability | A source file was accepted or partially accepted. |
| `ledgerlens.transaction.normalized` | normalization service | Go match worker | A raw row was normalized into canonical transaction shape. |
| `ledgerlens.match.candidate_created` | Go match worker or Python matcher | Python matching pipeline | A bounded candidate pair was found for scoring or deterministic matching. |
| `ledgerlens.match.decision_created` | matching pipeline | reporting, audit | A candidate was decided by exact, rule, fuzzy, LLM, or human tier. |
| `ledgerlens.review.required` | matching pipeline | review workbench | A low-confidence or high-risk pair needs analyst review. |
| `ledgerlens.review.resolved` | review workbench | matching pipeline, audit | A reviewer resolved an exception. |
| `ledgerlens.report.generated` | reporting service | observability, integrations | A run report artifact was written. |

## Schema Files

Event schemas live in `contracts/schemas/`:

- `event-envelope.schema.json`
- `statement-ingested.schema.json`
- `transaction-normalized.schema.json`
- `match-candidate-created.schema.json`
- `match-decision-created.schema.json`
- `review-required.schema.json`
- `review-resolved.schema.json`
- `report-generated.schema.json`

## Go Worker Contract

The Go match worker consumes `ledgerlens.transaction.normalized` events and emits `ledgerlens.match.candidate_created` events. It does not call an LLM, create final match decisions, manage human review, or write reports.

Candidate creation is bounded by:

- same `run_id`
- same `currency`
- same absolute amount
- posting dates within the configured window
- shared normalized reference or shared loose fingerprint
- different transaction IDs and different account/source context

This keeps Kafka useful for the enterprise streaming path while preserving the core LedgerLens principle: deterministic work first, expensive reasoning later.
