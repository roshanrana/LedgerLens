# STATE — LedgerLens

**Phase:** 7 — 0.2 shipped; `make check` green locally: 105 tests, golden 6 / 6, review gate 1 / 1, card current, see `docs/05-langgraph-review-gate-design.md`
**Gate command:** `make check` (`python -m unittest discover -s tests`, `make golden-check`, `make card-check`)
**Local interpreter:** `.venv/Scripts/python.exe` (Windows) with `pip install -e .[dev]` plus langgraph, langgraph-checkpoint-sqlite, mcp
**Updated:** 2026-09-08

## Now / next

- Now: pushed; CI runs `make check`.
- Next (backlog): record one Ollama adjudication run and publish it as a recorded figure; one-to-many matching; HMAC on review resolutions.

## Task log

| Task | Status | Notes |
|---|---|---|
| LL-0 | done | design doc 05, masking module, STATE.md, deps, Makefile check target, CI |
| LL-1 | done | graph, gate, CLI/API; 10 tests |
| LL-2 | done | masking, live backends; 36 tests |
| LL-3 | done | MCP review server; 16 tests |
| LL-4 | done | golden harness gate replay, card, README/OVERVIEW/SHOWCASE/runbook/HLD note, profile |

## Deviations

- 0.1 design docs promised LangGraph; 0.2 delivers it (decision D-1 in doc 05).

## Blockers

- none
