# LedgerLens — Showcase

A guided tour of the features, with the commands that show them and the files where they live. [OVERVIEW.md](OVERVIEW.md) covers the reasoning.

## Five minutes

```bash
python -m ledgerlens.cli --db .ledgerlens/ledgerlens.db demo
python -m unittest discover -s tests
```

The demo ingests two synthetic sources, reconciles them, opens review tasks and writes a Markdown report. Open the report. It has three sections worth reading in order: source diagnostics (what was wrong with the inputs), the tier breakdown (how many pairs each tier resolved and how many the model saw), and the exceptions (what nobody could match, and why).

## Fifteen minutes, with Docker

```bash
python scripts/verify.py --docker required --kafka-smoke
```

This runs the Python suite, a CLI smoke, the Go worker tests inside a container, builds the worker image, replays real exported events through it in file mode, validates the Compose file, and round-trips events through Redpanda.

## Feature tour

### 1. Source onboarding by configuration (`ledgerlens/ingestion/profiles.py`, `configs/clients/`)

Compare `acme_bank.json` and `acme_ledger.json`: one source has debit and credit columns, the other has signed amounts; they use different date formats and different reference conventions. Both are described, not coded. `test_loads_client_mapping_profile_with_reconciliation_controls` covers the profile contract.

### 2. Ingestion with raw provenance (`ledgerlens/ingestion/csv_ingestor.py`, `csv_loader.py`)

File and row hashes, deterministic ids, and the original row payload stored alongside the normalised one. `test_csv_ingestion_preserves_raw_rows_and_file_idempotency` and `test_sqlite_store_is_idempotent_for_duplicate_source_files_and_rows` show that re-ingesting the same file changes nothing.

### 3. Normalisation to a canonical transaction (`ledgerlens/normalization/`)

Posting date, value date, amount, currency, direction, raw and normalised description, counterparty, reference, an exact fingerprint, a loose fingerprint, and quality flags. `test_normalizes_bank_debit_credit_rows_into_canonical_transactions` and `test_normalizes_ledger_signed_amount_rows_and_extracts_references` cover the two sign conventions.

### 4. Source diagnostics (`ledgerlens/normalization/normalize.py`)

Row counts, missing references, missing external ids, duplicate external ids, parse errors, quality-flag counts. The report leads with them, because most reconciliation pain is upstream data quality and a good engine says so before it starts matching.

### 5. The matching ladder (`ledgerlens/matching/engine.py`, `models.py`, `text.py`)

| Tier | Test that shows it |
|---|---|
| Exact fingerprint | `test_exact_fingerprint_match_is_deterministic` |
| Deterministic rules (date lag, reference variants) | `test_rule_match_handles_cross_source_date_lag_and_reference_variants` |
| Fuzzy scoring with a middle band | `test_fuzzy_scoring_marks_middle_band_as_ambiguous_for_llm` |
| The whole ladder on the demo data | `test_demo_reconciliation_uses_multiple_tiers_and_review` |

### 6. The adjudication boundary (`ledgerlens/llm/schemas.py`, `fake.py`, `cache.py`)

`schemas.py` is the contract: what the model is given and what it must return. `fake.py` implements it deterministically. `cache.py` persists decisions by pair in SQLite; `test_cached_fake_llm_avoids_duplicate_pair_adjudication` asserts a second run does not re-ask.

**Why it is interesting:** the boundary is the product. A live model slots in behind the same schema, and the tests do not change.

### 7. The bounded workflow (`ledgerlens/agents/workflow.py`)

A small, explicit graph of nodes with a bounded number of steps, no free-form loops. `test_workflow_runs_bounded_nodes_and_routes_ambiguous_llm_result_to_review` shows an unsure adjudication becoming a review task rather than a match.

### 8. Human review (`ledgerlens/api/resources.py`)

Review tasks are created by the workflow and resolved through the CLI or the API, with an audit event carrying the human decision: `test_api_resources_resolve_review_with_human_decision_and_audit`.

### 9. Atomic runs and persistence (`ledgerlens/persistence/sqlite_store.py`)

WAL mode, run-scoped tables, audit events, and rollback on late failure: `test_persistent_workflow_rolls_back_partial_run_on_late_failure`, `test_same_database_demo_runs_are_run_scoped`.

### 10. Reports (`ledgerlens/reporting/`)

`test_report_summarizes_tiers_exceptions_and_llm_savings` is the one to read: the report has to state what the model saved, not just what it decided.

### 11. Event contracts (`contracts/schemas/`, `ledgerlens/events.py`)

Seven event types under one envelope schema, with fixtures. `tests/contract/test_event_contracts.py` checks every example and fixture against its declared schema.

### 12. The Go match worker (`go/match-worker/`)

| Look at | What it shows |
|---|---|
| `internal/contracts/events.go`, `schema_test.go` | The Go side of the contract, tested against the same JSON Schemas |
| `internal/worker/processor.go` | Candidate generation from normalised-transaction events |
| `internal/transport/file.go`, `kafka.go` | File mode for demos, Kafka mode for the streaming profile; offsets commit after output is written |

The verifier feeds this worker with events exported from a real Python run, which is the honest way to test a cross-language boundary.

### 13. The API (`ledgerlens/api/server.py`)

Dependency-free JSON over HTTP. `tests/e2e/test_api_server.py` runs the demo, resolves a review task, runs custom source pairs, and checks that a bad payload returns a structured error rather than a stack trace.

## Things worth noticing

- **The report reports the model's cost avoided.** That is what an operations lead wants to see before agreeing to a live key.
- **Rejection happens before a run exists.** Unsupported source shapes are refused before anything is persisted.
- **The cross-language test uses real output, not a hand-written fixture.**
- **No key anywhere.** The fake adjudicator is a first-class implementation of the contract, not a stub that returns "match".

## Questions this project answers, and where

| Question | Where the answer lives |
|---|---|
| Why not send every pair to the model? | `matching/engine.py`: three tiers resolve most pairs for free, and the report shows the saving |
| How do you keep an LLM's decision auditable? | `llm/schemas.py` (structured in, structured out) and the audit events in `persistence/` |
| How do you onboard a new client's statement format? | A profile in `configs/clients/` and one focused test |
| What happens when the model is not sure? | `agents/workflow.py`: a review task, resolved by a person, recorded with an audit event |
| How do you scale candidate generation? | `go/match-worker/` over Kafka-compatible topics, validated by replaying real events |
| What happens if a run fails halfway? | Rollback; `test_persistent_workflow_rolls_back_partial_run_on_late_failure` |
