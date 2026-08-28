from __future__ import annotations

from pathlib import Path
from typing import Any

from ledgerlens.agents.workflow import ReconciliationWorkflow
from ledgerlens.events import normalized_transaction_events, normalized_transaction_events_ndjson
from ledgerlens.persistence import SQLiteStore
from ledgerlens.reporting.report import generate_markdown_report


ROOT = Path(__file__).resolve().parents[2]


def run_demo(db_path: str | Path, client_id: str = "acme") -> dict[str, Any]:
    return run_reconciliation(
        db_path,
        client_id=client_id,
        sources=[
            (ROOT / "data" / "samples" / "acme_bank_statement.csv", ROOT / "configs" / "clients" / "acme_bank.json"),
            (ROOT / "data" / "samples" / "acme_ledger_export.csv", ROOT / "configs" / "clients" / "acme_ledger.json"),
        ],
    )


def run_reconciliation(
    db_path: str | Path,
    *,
    client_id: str,
    sources: list[tuple[str | Path, str | Path]],
) -> dict[str, Any]:
    if len(sources) < 2:
        raise ValueError("at least two source/profile pairs are required")
    with _store(db_path) as store:
        workflow = ReconciliationWorkflow(store)
        result = workflow.run(client_id=client_id, sources=_normalize_sources(sources))
        return {
            "run_id": result.run_id,
            "report": generate_markdown_report(store, result.run_id),
            "counts": store.table_counts(result.run_id),
            "review_tasks": store.list_review_tasks(result.run_id),
            "source_count": len(sources),
        }


def get_report(db_path: str | Path, run_id: str) -> dict[str, Any]:
    with _store(db_path) as store:
        return {
            "run_id": run_id,
            "report": generate_markdown_report(store, run_id),
            "counts": store.table_counts(run_id),
            "decisions_by_tier": store.decisions_by_tier(run_id),
        }


def list_normalized_events(db_path: str | Path, run_id: str) -> list[dict[str, Any]]:
    with _store(db_path) as store:
        return normalized_transaction_events(store.list_normalized_transactions(run_id))


def export_normalized_events(db_path: str | Path, run_id: str) -> str:
    with _store(db_path) as store:
        return normalized_transaction_events_ndjson(store.list_normalized_transactions(run_id))


def list_review_tasks(
    db_path: str | Path,
    run_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    with _store(db_path) as store:
        return store.list_review_tasks(run_id=run_id, status=status)


def resolve_review_task(
    db_path: str | Path,
    task_id: str,
    *,
    decision: str,
    notes: str,
    reviewer: str = "analyst",
) -> dict[str, Any]:
    with _store(db_path) as store:
        human_decision = store.resolve_review_task(task_id, decision, notes, reviewer)
        review_task = _single_review_task(store, task_id)
        return {
            "review_task": review_task,
            "decision": {
                "id": human_decision.id,
                "run_id": human_decision.run_id,
                "candidate_pair_id": human_decision.candidate_pair_id,
                "decision": human_decision.decision,
                "tier": human_decision.tier,
                "confidence": human_decision.confidence,
                "reason_code": human_decision.reason_code,
                "review_task_id": human_decision.review_task_id,
                "decided_by": human_decision.decided_by,
            },
        }


class _store:
    def __init__(self, db_path: str | Path):
        self.store = SQLiteStore(db_path)

    def __enter__(self) -> SQLiteStore:
        self.store.initialize()
        return self.store

    def __exit__(self, *_exc: object) -> None:
        self.store.close()


def _single_review_task(store: SQLiteStore, task_id: str) -> dict[str, Any]:
    rows = [task for task in store.list_review_tasks() if task["id"] == task_id]
    if not rows:
        raise ValueError(f"review task not found: {task_id}")
    return rows[0]


def _normalize_sources(sources: list[tuple[str | Path, str | Path]]) -> list[tuple[Path, Path]]:
    normalized: list[tuple[Path, Path]] = []
    for csv_path, profile_path in sources:
        csv = Path(csv_path)
        profile = Path(profile_path)
        if not csv.exists():
            raise ValueError(f"source CSV does not exist: {csv}")
        if not profile.exists():
            raise ValueError(f"mapping profile does not exist: {profile}")
        normalized.append((csv, profile))
    return normalized
