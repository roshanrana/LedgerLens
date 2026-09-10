# Code graph (graphify)

LedgerLens carries an offline code knowledge graph built by [graphify](https://pypi.org/project/graphifyy/)
(tree-sitter over the AST, no LLM required for code). It answers "what depends on this?", "how do A and B
connect?" and "what is X?" from a few hundred tokens of scoped subgraph instead of a raw grep across 122 files.
An agent working in this repository should query the graph before opening files for a task.

Current build: **1654 nodes · 3366 edges · 131 communities** (123 shown, 8 thin communities omitted), extracted
from 122 files (~56,013 words) in well under a minute, entirely offline. Extraction was 88% EXTRACTED / 12%
INFERRED / 0% AMBIGUOUS relations. Full detail is in `graphify-out/GRAPH_REPORT.md` (committed; the other
`graphify-out/` artifacts — `graph.json`, `graph.html`, `cache/`, `manifest.json` — are gitignored and rebuilt
in seconds).

## Build and query

```bash
uv tool install graphifyy          # once per machine
graphify update .                  # rebuild the graph (AST-only, no API key); re-run after code changes
graphify explain "<class or module>"
graphify path "<A>" "<B>"
graphify affected "<symbol>" --depth 2
```

`graphify update .` is also wired into the Makefile as `make graph`.

## Three real queries

### 1. `graphify explain "TieredMatcher"` — the reconciliation engine's core class

```
Node: TieredMatcher
  ID:        matching_engine_tieredmatcher
  Source:    ledgerlens/matching/engine.py L148
  Type:      code
  Community: 1
  Degree:    17

Connections (17):
  --> NormalizedTransaction [uses] [INFERRED]
  <-- workflow.py [imports] [EXTRACTED]
  --> MatchingPolicy [uses] [INFERRED]
  <-- engine.py [contains] [EXTRACTED]
  --> CandidatePair [uses] [INFERRED]
  <-- __init__.py [imports] [EXTRACTED]
  --> MatchEvaluation [uses] [INFERRED]
  <-- .__init__() [calls] [EXTRACTED]
  --> .evaluate() [method] [EXTRACTED]
  --> .evaluate_fuzzy() [method] [EXTRACTED]
  <-- test_matching_engine.py [imports] [EXTRACTED]
  --> .evaluate_rule() [method] [EXTRACTED]
  <-- .test_exact_fingerprint_match_is_deterministic() [calls] [EXTRACTED]
  <-- .test_fuzzy_scoring_marks_middle_band_as_ambiguous_for_llm() [calls] [EXTRACTED]
  <-- .test_rule_match_handles_cross_source_date_lag_and_reference_variants() [calls] [EXTRACTED]
  --> .evaluate_exact() [method] [EXTRACTED]
  --> .__init__() [method] [EXTRACTED]
```

### 2. `graphify path "cli.py" "SQLiteStore"` — the CLI's entry to the SQLite store

```
Shortest path (2 hops):
  cli.py --imports [EXTRACTED]--> SQLiteStore <--uses [INFERRED]-- SQLiteStore
```

### 3. `graphify affected "mask_transaction" --depth 2` — everyone who depends on the masking contract

```
Affected nodes for mask_transaction()
- __init__.py [imports] ledgerlens/llm/__init__.py:L1
- mask_pair() [calls] ledgerlens/llm/masking.py:L53
- schemas.py [imports] ledgerlens/llm/schemas.py:L1
- build_adjudication_request() [calls] ledgerlens/llm/schemas.py:L92
- test_masking.py [imports] tests/unit/test_masking.py:L1
- server.py [imports] ledgerlens/mcp/server.py:L1
- _get_review_pair() [calls] ledgerlens/mcp/server.py:L160
- cache.py / fake.py / live.py [imports_from] ledgerlens/llm/*.py:L1
- workflow.py [imports] ledgerlens/agents/workflow.py:L1
- .adjudicate_ambiguous_pairs() [calls] ledgerlens/agents/workflow.py:L491
- test_llm_cache.py, test_llm_live.py [imports/calls] tests/unit/*.py
```
(trimmed from 25 lines of output; the full list also names each masking test that calls it directly)

### What the graph got wrong

`graphify path "main" "SQLiteStore"` returned "no path found" with an ambiguity warning — `main` matches
several entry points across the repo (the Python CLI and the Go `match-worker`'s `main.go`), so the resolver
could not pick one confidently. Qualifying the source node as `"cli.py"` resolved it. The target side still
warned of an ambiguous match (two `SQLiteStore`-named nodes score identically) but returned the correct path
regardless.

## What `.graphifyignore` excludes

`.venv/`, `graphify-out/` (self-exclusion), `data/` (sample and golden fixture corpora), `node_modules/`,
`dist/`, `build/`, `.next/`, `htmlcov/`, `*.min.js`, `.ledgerlens/` (runtime SQLite databases),
`ledgerlens.egg-info/`, and Python cache directories (`__pycache__/`, `.pytest_cache/`, `.mypy_cache/`,
`.ruff_cache/`).

## The hooks (local opt-in, not committed)

`graphify install --project --platform claude` also offers PreToolUse hooks in `.claude/settings.json` that
intercept Read/Grep/Bash-search calls and nudge an agent toward `graphify query` first. Those hooks are
per-developer convenience, not repository policy, so they are not committed here — run the install command
yourself if you want them locally. `.claude/skills/graphify/` (the agent-facing skill) and the `## graphify`
section in the root `CLAUDE.md` are committed.

## Shipyard integration

Implementers query the graph before opening files for a task pack; Verifiers run `graphify affected` on every
symbol a diff touches and flag anything outside the pack's declared scope as a finding.
