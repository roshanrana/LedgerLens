# LedgerLens Go Match Worker

This sidecar is the optional Go/Kafka path from `docs/02-low-level-multi-agent-design.md`. It consumes normalized transaction events and emits bounded candidate-pair events for the downstream Python matching pipeline.

The worker is intentionally narrow:

- no LLM calls
- no final match decisions
- no review workflow
- no report generation
- no writes to Python application internals

## File Mode

File mode is the default and works without Kafka:

```bash
go run ./cmd/match-worker \
  --mode file \
  --input ../../contracts/events/fixtures/normalized-events.ndjson \
  --output candidates.ndjson
```

Input is newline-delimited JSON. Non-`ledgerlens.transaction.normalized` events are ignored.

## Kafka Mode

Kafka mode is opt-in:

```bash
go run ./cmd/match-worker \
  --mode kafka \
  --brokers localhost:19092 \
  --group ledgerlens-match-worker \
  --input-topic ledgerlens.transaction.normalized \
  --output-topic ledgerlens.match.candidate_created
```

The local `docker-compose.yml` defines a Redpanda broker under the `streaming` profile.
The worker fetches messages and commits offsets only after candidate events are successfully written.

Run the optional end-to-end smoke from the repository root:

```bash
python scripts/verify.py --docker required --kafka-smoke
```

## Candidate Rules

The worker emits `ledgerlens.match.candidate_created` when two normalized transactions have:

- same run
- same currency
- same absolute amount
- posting dates within `--max-date-window-days`
- different transaction IDs and different account/source context
- shared normalized reference or shared loose fingerprint

This is candidate generation only; confidence thresholds, final decisions, LLM escalation, and human review remain downstream responsibilities.
