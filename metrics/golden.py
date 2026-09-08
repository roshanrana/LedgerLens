"""Offline golden-metrics harness for LedgerLens.

Replays the bundled acme sample statements through the real reconciliation
workflow (temporary SQLite store, DeterministicFakeLLM), scores the run
against data/golden/expected_summary.json, validates every emitted event
against contracts/schemas/, and writes metrics/headline.json.

Every figure written is observed from that replay. Anything that would need
data or services the harness does not have (per-pair truth labels, a live
LLM, the Go worker) is reported in the facts panel with status "pending"
instead of being estimated.

Run with:  python -m metrics.golden   (or `make golden`)
"""
from __future__ import annotations

import asyncio
import csv
import json
import math
import sys
import tempfile
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import jsonschema

from ledgerlens.agents.workflow import ReconciliationWorkflow
from ledgerlens.events import normalized_transaction_events
from ledgerlens.ingestion.profiles import load_mapping_profile
from ledgerlens.matching.engine import MatchingConfig
from ledgerlens.persistence.store import SQLiteStore


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "metrics" / "headline.json"
GOLDEN_PATH = ROOT / "data" / "golden" / "expected_summary.json"
SAMPLES_DIR = ROOT / "data" / "samples"
PROFILES_DIR = ROOT / "configs" / "clients"
SCHEMAS_DIR = ROOT / "contracts" / "schemas"
EVENTS_DIR = ROOT / "contracts" / "events"

# Mirrors tests/golden/test_expected_summary.py so the harness scores exactly
# the replay that the golden test asserts against.
GOLDEN_CLIENT_ID = "acme"
GOLDEN_AMOUNT_TOLERANCE = Decimal("1.00")
GOLDEN_SOURCES = [
    (SAMPLES_DIR / "acme_bank_statement.csv", PROFILES_DIR / "acme_bank.json"),
    (SAMPLES_DIR / "acme_ledger_export.csv", PROFILES_DIR / "acme_ledger.json"),
]

# Same routing table the Python contract test and the Go worker use.
SCHEMA_BY_EVENT_TYPE = {
    "ledgerlens.statement.ingested": "statement-ingested.schema.json",
    "ledgerlens.transaction.normalized": "transaction-normalized.schema.json",
    "ledgerlens.match.candidate_created": "match-candidate-created.schema.json",
    "ledgerlens.match.decision_created": "match-decision-created.schema.json",
    "ledgerlens.review.required": "review-required.schema.json",
    "ledgerlens.review.resolved": "review-resolved.schema.json",
    "ledgerlens.report.generated": "report-generated.schema.json",
}

STRAIGHT_THROUGH_TIERS = {"exact", "rule", "fuzzy"}
PROFILE_REQUIRED_FIELDS = ("posting_date", "description")

ALLOWED_ACCENTS = {"teal", "blue", "amber", "violet", "red"}
ALLOWED_STATUSES = {"ok", "pending", "blocked"}
KPI_KEYS = {"label", "value", "note", "accent"}
BAR_ROW_KEYS = {"label", "value", "max", "display", "accent"}
FACT_ROW_KEYS = {"label", "value", "status"}


@dataclass(frozen=True)
class Replay:
    counts: dict[str, int]
    tiers: dict[str, int]
    decisions: list[dict[str, str]]
    report_summary: dict[str, Any]
    normalized_events: list[dict[str, Any]]
    unmatched_left: int
    unmatched_right: int
    llm_stats: dict[str, int]
    gate: "GateReplay"


@dataclass(frozen=True)
class GateReplay:
    """What the review gate did on the golden run, observed rather than asserted."""

    status_at_interrupt: str
    open_tasks_at_interrupt: int
    tasks_resolved: int
    resumed_status: str
    final_report_has_human_decision: bool
    final_report_has_finalized_event: bool
    checkpoints: int
    mcp_tools_listed: int
    mcp_tools_called: int
    mcp_raw_leaks: int
    masked_fields_per_side: int


@dataclass(frozen=True)
class ValidationResult:
    total: int
    valid: int
    failures: list[str] = field(default_factory=list)


def replay_golden_sources() -> Replay:
    """Run the persistent workflow on the golden sample pair in a temp SQLite store."""
    with tempfile.TemporaryDirectory() as tmp:
        store = SQLiteStore(Path(tmp) / "golden.db")
        store.initialize()
        try:
            workflow = ReconciliationWorkflow(store, MatchingConfig(amount_tolerance=GOLDEN_AMOUNT_TOLERANCE))
            result = workflow.run(GOLDEN_CLIENT_ID, GOLDEN_SOURCES)
            state = result.state
            summary = dict(state.report.summary) if state.report else {}
            # Snapshot the preliminary run exactly as before: the golden checks score this.
            counts = store.table_counts(result.run_id)
            tiers = store.decisions_by_tier(result.run_id)
            events = normalized_transaction_events(store.list_normalized_transactions(result.run_id))
            llm_stats = dict(workflow.llm.stats())
            gate = replay_review_gate(store, Path(tmp) / "golden.db", result.run_id, result.status)
            return Replay(
                counts=counts,
                tiers=tiers,
                decisions=[{"tier": decision.tier, "decision": decision.decision} for decision in state.decisions],
                report_summary=summary,
                normalized_events=events,
                unmatched_left=len(state.unmatched_transaction_ids.get("left", [])),
                unmatched_right=len(state.unmatched_transaction_ids.get("right", [])),
                llm_stats=llm_stats,
                gate=gate,
            )
        finally:
            store.close()


def replay_review_gate(store: SQLiteStore, db_path: Path, run_id: str, status_at_interrupt: str) -> GateReplay:
    """Resolve the open tasks as a human, then complete the review from a *second* workflow instance.

    Also drives the MCP review server over an in-memory client against the same database and
    checks that no raw counterparty or reference from the sample CSVs leaks through any tool.
    """
    open_tasks = store.list_review_tasks(run_id, status="open")
    mcp_listed, mcp_called, leaks, masked_fields = exercise_mcp_review(db_path, run_id, open_tasks)
    for task in open_tasks:
        suggested = task["suggested_decision"]
        decision = suggested if suggested in {"match", "no_match", "duplicate"} else "match"
        store.resolve_review_task(task["id"], decision, "resolved by the golden harness", "golden-harness")
    second_store = SQLiteStore(db_path)
    second_store.initialize()
    try:
        second = ReconciliationWorkflow(second_store, MatchingConfig(amount_tolerance=GOLDEN_AMOUNT_TOLERANCE))
        completion = second.complete_review(run_id, reviewer="golden-harness", note="golden replay")
        final_report = str(completion.get("report", ""))
        checkpoints = len(second.graph_history(run_id))
        resumed_status = str(second_store.get_run(run_id)["status"])
    finally:
        second_store.close()
    return GateReplay(
        status_at_interrupt=status_at_interrupt,
        open_tasks_at_interrupt=len(open_tasks),
        tasks_resolved=len(open_tasks),
        resumed_status=resumed_status,
        final_report_has_human_decision="human" in final_report,
        final_report_has_finalized_event="run.finalized" in final_report,
        checkpoints=checkpoints,
        mcp_tools_listed=mcp_listed,
        mcp_tools_called=mcp_called,
        mcp_raw_leaks=leaks,
        masked_fields_per_side=masked_fields,
    )


RAW_SAMPLE_COLUMNS = ("Counterparty", "Customer", "Reference", "Invoice", "Payee", "Memo")


def raw_sample_strings() -> set[str]:
    """Identifier-like values from the sample CSVs that must never leave the engine unmasked."""
    values: set[str] = set()
    for csv_path, _profile in GOLDEN_SOURCES:
        with csv_path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                for column in RAW_SAMPLE_COLUMNS:
                    value = (row.get(column) or "").strip()
                    if len(value) >= 4:
                        values.add(value)
    return values


def exercise_mcp_review(db_path: Path, run_id: str, open_tasks: list[dict[str, Any]]) -> tuple[int, int, int, int]:
    """Drive the MCP review server in-memory; return (tools listed, tools called, raw leaks, masked fields)."""
    from ledgerlens.mcp.server import build_server
    from mcp.client import Client

    raw = raw_sample_strings()
    server = build_server(db_path)

    async def drive() -> tuple[int, int, int, int]:
        called = 0
        leaks = 0
        masked_fields = 0
        async with Client(server) as client:
            tools = await client.list_tools()
            listed = len(tools.tools)
            calls: list[tuple[str, dict[str, Any]]] = [
                ("list_runs", {"limit": 5}),
                ("get_run", {"run_id": run_id}),
                ("list_review_tasks", {"run_id": run_id}),
                ("get_report", {"run_id": run_id}),
            ]
            if open_tasks:
                calls.append(("get_review_pair", {"task_id": open_tasks[0]["id"]}))
            for name, arguments in calls:
                result = await client.call_tool(name, arguments)
                payload = result.structured_content or {}
                called += 1
                text = json.dumps(payload, sort_keys=True)
                leaks += sum(1 for value in raw if value in text)
                if name == "get_review_pair" and "pair" in payload:
                    left = payload["pair"].get("left", {})
                    masked_fields = sum(
                        1 for key in ("reference_token", "counterparty_token", "description") if key in left
                    )
        return listed, called, leaks, masked_fields

    return asyncio.run(drive())


def golden_checks(replay: Replay, expected: dict[str, Any]) -> list[dict[str, Any]]:
    """The assertions from tests/golden/test_expected_summary.py, as pass/fail rows."""
    checks = [
        {
            "label": f"normalized_transactions == {expected['normalized_transactions']}",
            "passed": replay.counts["normalized_transactions"] == expected["normalized_transactions"],
        },
        {
            "label": f"candidate_pairs >= {expected['minimum_candidate_pairs']}",
            "passed": replay.counts["candidate_pairs"] >= expected["minimum_candidate_pairs"],
        },
        {
            "label": f"review_tasks >= {expected['minimum_review_tasks']}",
            "passed": replay.counts["review_tasks"] >= expected["minimum_review_tasks"],
        },
    ]
    for tier in expected["expected_decision_tiers"]:
        checks.append(
            {
                "label": f"decision tier '{tier}' present",
                "passed": any(key.startswith(f"{tier}:") for key in replay.tiers),
            }
        )
    return checks


def decision_routing(decisions: list[dict[str, str]]) -> dict[str, int]:
    straight_through = sum(
        1 for item in decisions if item["decision"] == "match" and item["tier"] in STRAIGHT_THROUGH_TIERS
    )
    review_required = sum(1 for item in decisions if item["decision"] == "needs_review")
    return {
        "total": len(decisions),
        "straight_through": straight_through,
        "review_required": review_required,
        "other": len(decisions) - straight_through - review_required,
    }


def load_validators() -> dict[str, jsonschema.Draft202012Validator]:
    validators: dict[str, jsonschema.Draft202012Validator] = {}
    for event_type, schema_name in SCHEMA_BY_EVENT_TYPE.items():
        schema = json.loads((SCHEMAS_DIR / schema_name).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        validators[event_type] = jsonschema.Draft202012Validator(schema)
    return validators


def validate_events(
    events: list[dict[str, Any]],
    validators: dict[str, jsonschema.Draft202012Validator],
) -> ValidationResult:
    failures: list[str] = []
    valid = 0
    for event in events:
        event_id = str(event.get("event_id", "<no event_id>"))
        validator = validators.get(str(event.get("event_type")))
        if validator is None:
            failures.append(f"{event_id}: unknown event_type {event.get('event_type')!r}")
            continue
        errors = [error.message for error in validator.iter_errors(event)]
        if errors:
            failures.extend(f"{event_id}: {message}" for message in errors)
            continue
        valid += 1
    return ValidationResult(total=len(events), valid=valid, failures=failures)


def load_fixture_events() -> list[dict[str, Any]]:
    paths = sorted(EVENTS_DIR.glob("*.example.json")) + sorted((EVENTS_DIR / "fixtures").glob("*.json"))
    events = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    for ndjson_path in sorted((EVENTS_DIR / "fixtures").glob("*.ndjson")):
        lines = ndjson_path.read_text(encoding="utf-8").splitlines()
        events.extend(json.loads(line) for line in lines if line.strip())
    return events


def csv_row_count(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def csv_header(path: Path) -> set[str]:
    with path.open(encoding="utf-8", newline="") as handle:
        return set(next(csv.reader(handle)))


def profile_maps_csv(profile_path: Path, csv_path: Path) -> bool:
    profile = load_mapping_profile(profile_path)
    required_columns = {profile.column_map[field_name] for field_name in PROFILE_REQUIRED_FIELDS}
    return required_columns <= csv_header(csv_path)


def samples_without_profile() -> list[Path]:
    replayed = {csv_path for csv_path, _profile in GOLDEN_SOURCES}
    profiles = sorted(PROFILES_DIR.glob("*.json"))
    unprofiled = []
    for sample in sorted(SAMPLES_DIR.glob("*.csv")):
        if sample in replayed:
            continue
        if not any(profile_maps_csv(profile, sample) for profile in profiles):
            unprofiled.append(sample)
    return unprofiled


def percent(numerator: int, denominator: int) -> str:
    return f"{round(100 * numerator / denominator)}%"


def build_kpis(
    replay: Replay,
    checks: list[dict[str, Any]],
    routing: dict[str, int],
    emitted: ValidationResult,
) -> dict[str, dict[str, str]]:
    passed = sum(1 for check in checks if check["passed"])
    kpis: dict[str, dict[str, str]] = {
        "golden_checks": {
            "label": "Golden checks passed",
            "value": f"{passed} / {len(checks)}",
            "note": "acme replay scored against data/golden/expected_summary.json",
            "accent": "teal" if passed == len(checks) else "red",
        }
    }
    if routing["total"]:
        kpis.update(_rate_kpis(replay, routing))
    kpis["schema_conformance"] = {
        "label": "Schema conformance",
        "value": f"{emitted.valid} / {emitted.total}",
        "note": "emitted transaction.normalized events validated against contracts/schemas (Draft 2020-12, structural)",
        "accent": "teal" if emitted.valid == emitted.total else "red",
    }
    kpis["review_gate"] = _review_gate_kpi(replay.gate)
    return kpis


def _review_gate_kpi(gate: GateReplay) -> dict[str, str]:
    gated = gate.status_at_interrupt == "awaiting_review"
    resumed = (
        gate.resumed_status == "completed"
        and gate.final_report_has_human_decision
        and gate.final_report_has_finalized_event
    )
    passed = 1 if gated and resumed else 0
    return {
        "label": "Review gate",
        "value": f"{passed} / 1",
        "note": (
            f"run paused at await_review with {gate.open_tasks_at_interrupt} open task(s); resumed by a second "
            "workflow instance after human resolution; final report carries the human decision"
        ),
        "accent": "teal" if passed else "red",
    }


def _rate_kpis(replay: Replay, routing: dict[str, int]) -> dict[str, dict[str, str]]:
    total = routing["total"]
    matched = int(replay.report_summary.get("matched_decisions", 0))
    matched_by_tier = {
        key.split(":", 1)[0]: count for key, count in sorted(replay.tiers.items()) if key.endswith(":match")
    }
    tier_text = ", ".join(f"{tier} {count}" for tier, count in matched_by_tier.items()) or "none"
    return {
        "match_rate": {
            "label": "Match rate",
            "value": percent(matched, total),
            "note": f"{matched} of {total} candidate decisions matched ({tier_text})",
            "accent": "blue",
        },
        "straight_through_rate": {
            "label": "Straight-through",
            "value": percent(routing["straight_through"], total),
            "note": f"{routing['straight_through']} of {total} decisions closed by exact/rule/fuzzy tiers without review",
            "accent": "violet",
        },
        "review_required_rate": {
            "label": "Review required",
            "value": percent(routing["review_required"], total),
            "note": f"{routing['review_required']} of {total} decisions routed to a human review task",
            "accent": "amber",
        },
    }


def build_bars(replay: Replay, routing: dict[str, int]) -> dict[str, Any]:
    total = routing["total"]
    normalized = replay.counts["normalized_transactions"]
    unmatched = replay.unmatched_left + replay.unmatched_right
    rows = [
        {
            "label": "Straight-through matches",
            "value": routing["straight_through"],
            "max": total,
            "display": f"{routing['straight_through']} of {total} decisions",
            "accent": "teal",
        },
        {
            "label": "Review required",
            "value": routing["review_required"],
            "max": total,
            "display": f"{routing['review_required']} of {total} decisions",
            "accent": "amber",
        },
    ]
    if routing["other"]:
        rows.append(
            {
                "label": "Auto no-match / other",
                "value": routing["other"],
                "max": total,
                "display": f"{routing['other']} of {total} decisions",
                "accent": "blue",
            }
        )
    rows.append(
        {
            "label": "Unmatched transactions",
            "value": unmatched,
            "max": normalized,
            "display": f"{unmatched} of {normalized} transactions ({replay.unmatched_left} bank, {replay.unmatched_right} ledger)",
            "accent": "red",
        }
    )
    return {"title": "Decision routing (acme replay)", "rows": rows}


def build_facts(replay: Replay, fixtures: ValidationResult, unprofiled: list[Path]) -> dict[str, Any]:
    sources = " + ".join(f"{csv_path.name} ({csv_row_count(csv_path)} rows)" for csv_path, _profile in GOLDEN_SOURCES)
    llm = replay.llm_stats
    rows = [
        {
            "label": "Samples replayed",
            "value": f"{sources} -> {replay.counts['normalized_transactions']} normalized transactions",
            "status": "ok",
        },
        _unprofiled_fact(unprofiled),
        {
            "label": "Precision / recall / F1",
            "value": "expected_summary.json carries aggregate thresholds only; no per-pair match labels to score against",
            "status": "pending",
        },
        {
            "label": "Contract fixtures validated",
            "value": f"{fixtures.valid} of {fixtures.total} events under contracts/events pass their declared schema",
            "status": "ok" if fixtures.valid == fixtures.total else "blocked",
        },
        {
            "label": "Fake-LLM adjudications",
            "value": f"calls {llm.get('calls', 0)}, cache hits {llm.get('cache_hits', 0)} (DeterministicFakeLLM, offline)",
            "status": "ok",
        },
        {
            "label": "LangGraph checkpoints",
            "value": (
                f"{replay.gate.checkpoints} checkpoints for the gated run in the run database "
                "(SqliteSaver, thread_id = run_id); every step replayable with graph-history"
            ),
            "status": "ok" if replay.gate.checkpoints >= 13 else "blocked",
        },
        {
            "label": "Cross-instance resume",
            "value": (
                f"status {replay.gate.status_at_interrupt} at the interrupt; {replay.gate.tasks_resolved} task(s) "
                f"resolved as a human; a second workflow instance completed the review -> {replay.gate.resumed_status}"
            ),
            "status": "ok" if replay.gate.resumed_status == "completed" else "blocked",
        },
        {
            "label": "MCP review tools",
            "value": (
                f"{replay.gate.mcp_tools_called} of {replay.gate.mcp_tools_listed} tools called over an in-memory MCP "
                f"session; {replay.gate.mcp_raw_leaks} raw counterparty/reference strings from the samples leaked"
            ),
            "status": "ok" if replay.gate.mcp_raw_leaks == 0 and replay.gate.mcp_tools_called else "blocked",
        },
        {
            "label": "Payload masking",
            "value": (
                f"{replay.gate.masked_fields_per_side} of 3 sensitive fields per side tokenised or redacted "
                "(reference, counterparty, description) under ledgerlens.masking.v1, for the model and for MCP"
            ),
            "status": "ok" if replay.gate.masked_fields_per_side == 3 else "blocked",
        },
        {
            "label": "Live LLM adjudication",
            "value": (
                "openai_compat (Ollama, vLLM), bedrock and anthropic adapters ship behind the same contract; "
                "the harness runs the deterministic fake with no key, so live accuracy is not measured"
            ),
            "status": "pending",
        },
        {
            "label": "Go match-worker candidates",
            "value": "not executed by this harness; covered by go test in go/match-worker",
            "status": "pending",
        },
    ]
    return {"title": "Replay evidence", "rows": rows}


def _unprofiled_fact(unprofiled: list[Path]) -> dict[str, str]:
    if not unprofiled:
        return {"label": "Samples without a profile", "value": "every sample CSV has a mapping profile", "status": "ok"}
    names = ", ".join(path.name for path in unprofiled)
    return {
        "label": "Samples without a profile",
        "value": f"{names}: no profile under configs/clients maps their headers, so they were not replayed",
        "status": "pending",
    }


def build_headline() -> dict[str, Any]:
    expected = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    replay = replay_golden_sources()
    checks = golden_checks(replay, expected)
    routing = decision_routing(replay.decisions)
    validators = load_validators()
    emitted = validate_events(replay.normalized_events, validators)
    fixtures = validate_events(load_fixture_events(), validators)
    return {
        "kpis": build_kpis(replay, checks, routing, emitted),
        "bars": build_bars(replay, routing),
        "facts": build_facts(replay, fixtures, samples_without_profile()),
    }


def validate_headline(headline: Any) -> list[str]:
    """Self-check against the card schema. Returns a list of problems (empty when valid)."""
    if not isinstance(headline, dict):
        return ["headline must be a JSON object"]
    problems = [f"missing top-level key '{key}'" for key in ("kpis", "bars", "facts") if key not in headline]
    if problems:
        return problems
    problems.extend(_validate_kpis(headline["kpis"]))
    problems.extend(_validate_bars(headline["bars"]))
    problems.extend(_validate_facts(headline["facts"]))
    return problems


def _validate_kpis(kpis: Any) -> list[str]:
    if not isinstance(kpis, dict) or not kpis:
        return ["kpis must be a non-empty object"]
    problems: list[str] = []
    for key, tile in kpis.items():
        problems.extend(_check_keys(f"kpis.{key}", tile, KPI_KEYS))
        if isinstance(tile, dict) and tile.get("accent") not in ALLOWED_ACCENTS:
            problems.append(f"kpis.{key}.accent {tile.get('accent')!r} not in {sorted(ALLOWED_ACCENTS)}")
    return problems


def _validate_bars(bars: Any) -> list[str]:
    problems = _check_keys("bars", bars, {"title", "rows"})
    if problems:
        return problems
    for index, row in enumerate(bars["rows"]):
        prefix = f"bars.rows[{index}]"
        problems.extend(_check_keys(prefix, row, BAR_ROW_KEYS))
        if not isinstance(row, dict):
            continue
        if row.get("accent") not in ALLOWED_ACCENTS:
            problems.append(f"{prefix}.accent {row.get('accent')!r} not in {sorted(ALLOWED_ACCENTS)}")
        problems.extend(_check_bar_range(prefix, row.get("value"), row.get("max")))
    return problems


def _check_bar_range(prefix: str, value: Any, maximum: Any) -> list[str]:
    if not _is_number(value) or not _is_number(maximum):
        return [f"{prefix}.value and .max must be finite numbers"]
    if value < 0 or maximum < 0:
        return [f"{prefix}.value and .max must be non-negative"]
    if value > maximum:
        return [f"{prefix}.value {value} exceeds max {maximum}"]
    return []


def _validate_facts(facts: Any) -> list[str]:
    problems = _check_keys("facts", facts, {"title", "rows"})
    if problems:
        return problems
    for index, row in enumerate(facts["rows"]):
        prefix = f"facts.rows[{index}]"
        problems.extend(_check_keys(prefix, row, FACT_ROW_KEYS))
        if isinstance(row, dict) and row.get("status") not in ALLOWED_STATUSES:
            problems.append(f"{prefix}.status {row.get('status')!r} not in {sorted(ALLOWED_STATUSES)}")
    return problems


def _check_keys(prefix: str, item: Any, required: set[str]) -> list[str]:
    if not isinstance(item, dict):
        return [f"{prefix} must be an object"]
    problems = [f"{prefix} missing key '{key}'" for key in sorted(required - set(item))]
    for key in ("label", "note", "display", "title"):
        if key in required and key in item and not isinstance(item[key], str):
            problems.append(f"{prefix}.{key} must be a string")
    if "rows" in required and not isinstance(item.get("rows"), list):
        problems.append(f"{prefix}.rows must be a list")
    return problems


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def write_headline(headline: dict[str, Any], output_path: Path = OUTPUT_PATH) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(headline, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    output_path = Path(argv[0]) if argv else OUTPUT_PATH
    headline = build_headline()
    problems = validate_headline(headline)
    if problems:
        for problem in problems:
            print(f"headline self-check failed: {problem}", file=sys.stderr)
        return 1
    write_headline(headline, output_path)
    print(f"wrote {output_path}")
    for key, tile in headline["kpis"].items():
        print(f"  {key}: {tile['value']}  ({tile['note']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
