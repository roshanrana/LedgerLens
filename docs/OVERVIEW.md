# LedgerLens — Overview

**What it is:** a reconciliation engine that uses a language model the way a careful operations team would use a specialist: rarely, only for the cases that need judgement, with the question and the answer written down.

**Read this if** you want the problem and the design rationale. [SHOWCASE.md](SHOWCASE.md) walks the features with commands.

---

## The setting

Every finance function reconciles. Treasury matches bank statements to the cash ledger. Operations matches processor settlement files to the sales ledger. A fund administrator matches custodian positions to the book of record. The files never share a schema. One side carries signed amounts; the other carries debit and credit columns. The bank posts on Monday what the ledger booked on Friday. References are truncated, descriptions are abbreviated differently by every system, and the same transaction id appears twice because an upstream job re-ran.

Most rows match trivially. The cost lives in the residue: the pairs that look alike but are not, and the pairs that are the same transaction wearing two descriptions. Historically that residue is a spreadsheet and an analyst's afternoon. The tempting modern answer is to hand every candidate pair to a language model. It is the wrong answer for three reasons: it costs money on every run, it cannot be explained to an auditor, and it is slower and less reliable than a rule for the cases a rule can handle.

LedgerLens is built around the right answer: a ladder.

## The design

**Rules first, because rules are cheaper and more reliable where they apply.** Exact fingerprints catch identical transactions. Deterministic rules catch the known finance patterns: a one-to-three-day posting lag, reference variants, sign conventions. Fuzzy scoring over normalised descriptions, amounts and dates handles near-misses and produces a band: high scores match, low scores become exceptions, and only the middle band goes any further.

**A model only for the middle band, behind a contract.** The adjudicator receives a structured question (two normalised transactions, their diagnostics, a bounded set of fields) and returns a structured answer (a decision, a confidence, a reason). Its decisions are cached by pair in SQLite, so a re-run never asks the same question twice. The report states what the model was asked, what it was not asked, and what the difference saved.

**Humans for what the model is unsure about.** A low-confidence adjudication becomes a review task rather than a match. Review resolutions are persisted with an audit event and a human decision, and the report shows them.

**Atomic runs.** A run that fails late rolls back completely; `test_persistent_workflow_rolls_back_partial_run_on_late_failure` proves it. Two demo runs against the same database are scoped to their run ids and do not contaminate each other.

**Everything is an event.** Ingestion, normalisation, candidates, decisions, review, reports: each has a JSON Schema contract in `contracts/schemas/`, and the Go match worker consumes the same events the Python engine exports. The streaming profile is optional, but the contracts are not.

## Why a Go sidecar

Candidate generation is the part of reconciliation that scales with volume squared, and it is embarrassingly parallel. A Go worker over a Kafka-compatible log is where that belongs in production. The worker here is small and deliberately validated the honest way: events exported from a real Python reconciliation run are replayed through the Go binary, and the output has to match the contract the Python side declared. Kafka offsets commit only after candidate events are written, so a worker crash re-delivers rather than drops.

## What is measured

| Claim | Evidence |
|---|---|
| Tiered matching uses every tier and routes the ambiguous band to review | `test_demo_reconciliation_uses_multiple_tiers_and_review` |
| The model never sees the same pair twice | `test_cached_fake_llm_avoids_duplicate_pair_adjudication`, `test_sqlite_llm_cache_persists_structured_decisions` |
| Late failure leaves no partial run behind | `test_persistent_workflow_rolls_back_partial_run_on_late_failure` |
| Duplicate source files and rows are idempotent | `test_sqlite_store_is_idempotent_for_duplicate_source_files_and_rows` |
| Upstream data-quality problems are surfaced, not hidden | `test_ingestion_diagnostics_surface_client_data_quality_issues`, `test_source_diagnostics_finds_duplicate_reference` |
| Python-exported events fit the Go worker's contract | `test_normalized_events_export_matches_go_worker_contract_shape` and the Go `schema_test.go` |
| The demo's summary matches a golden shape | `tests/golden/test_expected_summary.py` against `data/golden/expected_summary.json` |
| Unsupported source shapes are rejected before a run is created | `test_reconciliation_rejects_unsupported_source_shapes_before_run_creation` |

## Honest limits

The adjudicator that ships is a deterministic fake implementing the live contract; the live provider is a binding change and has not been exercised here. Matching is pairwise within bounded candidate windows; one-to-many and many-to-many matching are not implemented. Sample data is synthetic. The streaming profile validates the boundary, not throughput.

## Where it sits among the other projects

LedgerLens is the engine that [HARBORMASTER](https://github.com/roshanrana/Harbormaster) feeds: Harbormaster decides which files, which client and which value date; LedgerLens decides which rows match. [SHADOWBOOK](https://github.com/roshanrana/shadowbook) applies the same reconciliation instinct between two ledgers rather than two files. The three-tier ladder here is the same idea as Harbormaster's mapping ladder, applied to rows instead of columns.
