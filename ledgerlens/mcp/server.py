"""LedgerLens MCP review server (docs/05-langgraph-review-gate-design.md section 6).

Any MCP client (Claude Desktop, Cursor, a script) can list reconciliation runs, read the
review tasks the matching engine raised, inspect a *masked* candidate pair, resolve a task
and complete the review. Two invariants hold across the MCP boundary:

* Data perimeter: candidate pairs leave only through ``ledgerlens.llm.masking.mask_pair``.
  A raw counterparty, raw reference or unmasked description is never returned by any tool.
* Human authority: ``resolve_review_task`` requires a named ``reviewer`` and non-empty
  ``notes``; ``complete_review`` refuses while the run still has open review tasks.

Every tool returns a JSON-serialisable dict and never raises across the wire: failures
(unknown ids, bad decisions, closed tasks) come back as ``{"error": "..."}``. Every tool
opens its own ``SQLiteStore`` and closes it before returning, so the server holds no
connection between calls and the database file can be moved or deleted between calls.

Run standalone with ``python -m ledgerlens.mcp.server`` (stdio transport) or
``ledgerlens mcp``. ``LEDGERLENS_DB`` overrides the default database location.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from ledgerlens.llm.masking import mask_pair
from ledgerlens.persistence.store import SQLiteStore
from ledgerlens.reporting.report import generate_markdown_report

SERVER_NAME = "ledgerlens-review"
ENV_DB_PATH = "LEDGERLENS_DB"
DEFAULT_DB_PATH = Path(".ledgerlens") / "ledgerlens.db"
DEFAULT_LIST_LIMIT = 20
COMPLETION_UNAVAILABLE = "review completion not available"
TOOL_NAMES: tuple[str, ...] = (
    "list_runs",
    "get_run",
    "list_review_tasks",
    "get_review_pair",
    "resolve_review_task",
    "complete_review",
    "get_report",
)
_MACHINE_DECISION_FIELDS = ("id", "tier", "decision", "confidence", "reason_code", "explanation")

_INSTRUCTIONS = (
    "Human review gate for LedgerLens financial reconciliation runs. A run matches bank and "
    "ledger transactions in tiers (exact, rule, llm) and raises a review task for every pair "
    "the machine could not settle. Use list_runs and list_review_tasks to find open work, "
    "get_review_pair to inspect the MASKED candidate pair together with the machine's "
    "decision and reasoning, then resolve_review_task with your decision, notes and name. "
    "Once no tasks are open, complete_review finalises the run. Counterparties and "
    "references are replaced by hashed tokens; this server never reveals the raw values. "
    'Every tool returns a JSON object; failures are reported as {"error": "..."}.'
)


# --------------------------------------------------------------------------- #
# Store lifecycle and guarding                                                 #
# --------------------------------------------------------------------------- #


@contextmanager
def _open_store(db_path: Path) -> Iterator[SQLiteStore]:
    """Open, initialise and always close a store; one per tool call."""
    store = SQLiteStore(db_path)
    try:
        store.initialize()
        yield store
    finally:
        store.close()


def _require(value: str | None, field: str) -> str:
    """Return ``value`` stripped, or raise if blank; review decisions need a named human."""
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValueError(f"{field} is required and must not be empty")
    return cleaned


def _guard(fn: Callable[..., dict[str, Any]], *args: Any) -> dict[str, Any]:
    """Run a tool body; any exception becomes an error dict instead of crossing the wire.

    ``ValueError`` carries the store's own message (unknown id, unsupported decision, task
    already resolved); anything else keeps its type name so the detail is not lost to the
    server's stderr.
    """
    try:
        return fn(*args)
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - the MCP boundary must not raise
        return {"error": f"{type(exc).__name__}: {exc}"}


def _single_review_task(store: SQLiteStore, task_id: str) -> dict[str, Any]:
    rows = [task for task in store.list_review_tasks() if task["id"] == task_id]
    if not rows:
        raise ValueError(f"review task not found: {task_id}")
    return rows[0]


def _machine_decision(store: SQLiteStore, run_id: str, pair_id: str) -> dict[str, Any] | None:
    """The latest non-human decision recorded for ``pair_id``, trimmed to its reasoning."""
    candidates = [
        decision
        for decision in store.list_match_decisions(run_id)
        if decision["candidate_pair_id"] == pair_id and decision["tier"] != "human"
    ]
    if not candidates:
        return None
    latest = candidates[-1]
    return {field: latest.get(field) for field in _MACHINE_DECISION_FIELDS}


def _load_complete_review() -> Callable[..., Any] | None:
    """``ledgerlens.api.resources.complete_review`` if LL-1 has landed, else ``None``."""
    from ledgerlens.api import resources

    service = getattr(resources, "complete_review", None)
    return service if callable(service) else None


# --------------------------------------------------------------------------- #
# Tool bodies (raise freely; ``_guard`` converts to {"error": ...})            #
# --------------------------------------------------------------------------- #


def _list_runs(db_path: Path, limit: int) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    with _open_store(db_path) as store:
        return {"runs": store.list_runs(limit)}


def _get_run(db_path: Path, run_id: str) -> dict[str, Any]:
    with _open_store(db_path) as store:
        return {
            "run": store.get_run(run_id),
            "open_review_tasks": store.open_review_task_count(run_id),
            "counts": store.table_counts(run_id),
            "decisions_by_tier": store.decisions_by_tier(run_id),
        }


def _list_review_tasks(db_path: Path, run_id: str, status: str | None) -> dict[str, Any]:
    with _open_store(db_path) as store:
        store.get_run(run_id)  # unknown run -> error rather than an empty list
        tasks = store.list_review_tasks(run_id=run_id, status=status or None)
        return {"run_id": run_id, "status": status or None, "tasks": tasks}


def _get_review_pair(db_path: Path, task_id: str) -> dict[str, Any]:
    with _open_store(db_path) as store:
        task = _single_review_task(store, task_id)
        pair = store.get_candidate_pair(task["candidate_pair_id"])
        return {
            "task": task,
            "pair": mask_pair(pair),
            "machine_decision": _machine_decision(store, task["run_id"], task["candidate_pair_id"]),
        }


def _resolve_review_task(
    db_path: Path, task_id: str, decision: str, notes: str, reviewer: str
) -> dict[str, Any]:
    who = _require(reviewer, "reviewer")
    why = _require(notes, "notes")
    with _open_store(db_path) as store:
        human_decision = store.resolve_review_task(task_id, decision, why, who)
        return {"task": _single_review_task(store, task_id), "decision": asdict(human_decision)}


def _complete_review(db_path: Path, run_id: str, reviewer: str, note: str) -> dict[str, Any]:
    who = _require(reviewer, "reviewer")
    with _open_store(db_path) as store:
        store.get_run(run_id)
        open_count = store.open_review_task_count(run_id)
    if open_count:
        raise ValueError(
            f"run {run_id} still has {open_count} open review task(s); resolve them before completing"
        )
    service = _load_complete_review()
    if service is None:
        raise ValueError(COMPLETION_UNAVAILABLE)
    result = service(db_path, run_id, reviewer=who, note=note or "")
    return result if isinstance(result, dict) else {"result": result}


def _get_report(db_path: Path, run_id: str) -> dict[str, Any]:
    with _open_store(db_path) as store:
        store.get_run(run_id)
        return {
            "run_id": run_id,
            "report": generate_markdown_report(store, run_id),
            "counts": store.table_counts(run_id),
            "decisions_by_tier": store.decisions_by_tier(run_id),
        }


# --------------------------------------------------------------------------- #
# Server                                                                       #
# --------------------------------------------------------------------------- #


def build_server(db_path: str | Path) -> MCPServer[Any]:
    """Build the ``ledgerlens-review`` server over the SQLite database at ``db_path``."""
    path = Path(db_path)
    server: MCPServer[Any] = MCPServer(SERVER_NAME, instructions=_INSTRUCTIONS)

    @server.tool()
    def list_runs(limit: int = DEFAULT_LIST_LIMIT) -> dict[str, Any]:
        """List the most recent reconciliation runs, newest first.

        Result: {"runs": [{"id", "client_id", "status", "created_at", "completed_at",
        "metadata"}]}. status is one of created, awaiting_review, completed, failed. Use a
        run's id with get_run, list_review_tasks, complete_review or get_report. A limit
        below 1 returns an error.
        """
        return _guard(_list_runs, path, limit)

    @server.tool()
    def get_run(run_id: str) -> dict[str, Any]:
        """Return one run with its open-task count, table counts and decisions by tier.

        Result: {"run": {...}, "open_review_tasks": n, "counts": {"normalized_transactions",
        "candidate_pairs", "match_decisions", "review_tasks", ...}, "decisions_by_tier":
        {"exact:match": n, "llm:needs_review": n, ...}}. Unknown run_id returns an error.
        """
        return _guard(_get_run, path, run_id)

    @server.tool()
    def list_review_tasks(run_id: str, status: str | None = None) -> dict[str, Any]:
        """List the review tasks of a run, optionally filtered by status ('open' or 'resolved').

        Result: {"run_id", "status", "tasks": [{"id", "candidate_pair_id", "priority",
        "status", "reason", "suggested_decision", "assigned_to", "reviewer_decision",
        "reviewer_notes", "created_at", "resolved_at"}]}. Pass a task id to get_review_pair
        to see what the reviewer must decide. Unknown run_id returns an error.
        """
        return _guard(_list_review_tasks, path, run_id, status)

    @server.tool()
    def get_review_pair(task_id: str) -> dict[str, Any]:
        """Return the MASKED candidate pair behind a review task plus the machine's decision.

        Result: {"task": {...}, "pair": {"pair_id", "run_id", "left", "right", "features",
        "blocking_reason", "masking_version"}, "machine_decision": {"tier", "decision",
        "confidence", "reason_code", "explanation"} or null}. Each side keeps id, date,
        amount, currency and source_system; reference and counterparty are hashed tokens
        (equal tokens mean equal values) and the description has long digit runs redacted.
        The raw counterparty and reference are never returned. Unknown task_id returns an
        error.
        """
        return _guard(_get_review_pair, path, task_id)

    @server.tool()
    def resolve_review_task(task_id: str, decision: str, notes: str, reviewer: str) -> dict[str, Any]:
        """Record a human decision on an open review task.

        decision is one of match, no_match, duplicate, needs_review, unmatched. notes (why)
        and reviewer (who) are both required and must be non-empty; the server never decides
        on its own. Result: {"task": {...status "resolved"...}, "decision": {tier "human",
        confidence 1.0, ...}}. A task that is unknown or already resolved returns an error.
        """
        return _guard(_resolve_review_task, path, task_id, decision, notes, reviewer)

    @server.tool()
    def complete_review(run_id: str, reviewer: str, note: str = "") -> dict[str, Any]:
        """Complete the review of a run once every review task has been resolved.

        reviewer must be the non-empty name of the human signing off. Refuses with an error
        while the run still has open review tasks; resolve them first with
        resolve_review_task. Returns the completion record from the reconciliation service
        (run status becomes 'completed'), or {"error": "review completion not available"}
        when the service does not support completion in this build.
        """
        return _guard(_complete_review, path, run_id, reviewer, note)

    @server.tool()
    def get_report(run_id: str) -> dict[str, Any]:
        """Return the Markdown reconciliation report of a run with its summary counts.

        Result: {"run_id", "report": "<markdown>", "counts": {...}, "decisions_by_tier":
        {...}}. The report contains aggregate figures, tier breakdowns and audit event
        counts only; no transaction-level data. Unknown run_id returns an error.
        """
        return _guard(_get_report, path, run_id)

    return server


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #


def db_path_from_env(environ: dict[str, str] | None = None) -> Path:
    """Database path from ``LEDGERLENS_DB``, defaulting to ``.ledgerlens/ledgerlens.db``."""
    env = os.environ if environ is None else environ
    return Path(env.get(ENV_DB_PATH) or DEFAULT_DB_PATH)


def main() -> None:
    """Entry point for ``python -m ledgerlens.mcp.server`` and ``ledgerlens mcp``: serve over stdio."""
    build_server(db_path_from_env()).run("stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
