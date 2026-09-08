from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ledgerlens.api.resources import (
    LLM_BACKENDS,
    complete_review,
    export_normalized_events,
    get_run,
    graph_history,
    run_demo,
    run_reconciliation,
)
from ledgerlens.persistence.store import SQLiteStore
from ledgerlens.reporting.report import generate_markdown_report


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / ".ledgerlens" / "ledgerlens.db"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ledgerlens", description="LedgerLens reconciliation CLI")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="Initialize the SQLite database")
    demo = sub.add_parser("demo", help="Run the bundled bank-vs-ledger reconciliation demo")
    demo.add_argument("--client-id", default="acme")
    demo.add_argument("--llm", default="fake", choices=LLM_BACKENDS, help="Adjudicator backend (default: fake)")
    reconcile = sub.add_parser("reconcile", help="Run reconciliation for custom CSV/profile pairs")
    reconcile.add_argument("--client-id", required=True)
    reconcile.add_argument("--llm", default="fake", choices=LLM_BACKENDS, help="Adjudicator backend (default: fake)")
    reconcile.add_argument(
        "--source",
        action="append",
        nargs=2,
        metavar=("CSV_PATH", "PROFILE_PATH"),
        required=True,
        help="Add one source CSV plus its mapping profile. Provide at least two.",
    )
    report = sub.add_parser("report", help="Print a report for a run")
    report.add_argument("run_id")
    export_events = sub.add_parser("export-normalized-events", help="Export normalized transaction events for a run as NDJSON")
    export_events.add_argument("run_id")
    export_events.add_argument("--output", default="-", help="Output path, or - for stdout")
    review = sub.add_parser("review-list", help="List review tasks")
    review.add_argument("--run-id")
    resolve = sub.add_parser("review-resolve", help="Resolve a review task")
    resolve.add_argument("task_id")
    resolve.add_argument("--decision", required=True, choices=["match", "no_match", "duplicate", "needs_review", "unmatched"])
    resolve.add_argument("--notes", default="")
    resolve.add_argument("--reviewer", default="analyst")
    complete = sub.add_parser("review-complete", help="Complete the review gate and finalize a run")
    complete.add_argument("run_id")
    complete.add_argument("--reviewer", required=True)
    complete.add_argument("--note", default="")
    history = sub.add_parser("graph-history", help="Print the LangGraph checkpoints of a run, oldest first")
    history.add_argument("run_id")
    status = sub.add_parser("run-status", help="Print the status of a run and its open review tasks")
    status.add_argument("run_id")
    sub.add_parser("mcp", help="Start the ledgerlens-review MCP server over stdio")
    serve_parser = sub.add_parser("serve", help="Run the local LedgerLens JSON API")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8080)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = SQLiteStore(args.db)
    store.initialize()
    try:
        if args.command == "init-db":
            print(f"Initialized {args.db}")
            return 0
        if args.command in {"demo", "reconcile"}:
            store.close()
            return _run_command(args)
        if args.command == "report":
            print(generate_markdown_report(store, args.run_id))
            return 0
        if args.command == "export-normalized-events":
            store.close()
            return _export_command(args)
        if args.command == "review-list":
            for task in store.list_review_tasks(args.run_id):
                print(f"{task['id']} {task['status']} {task['priority']} {task['suggested_decision']} {task['reason']}")
            return 0
        if args.command == "review-resolve":
            store.resolve_review_task(args.task_id, args.decision, args.notes or "Resolved from CLI", args.reviewer)
            print(f"Resolved {args.task_id} as {args.decision}")
            return 0
        if args.command in {"review-complete", "graph-history", "run-status"}:
            store.close()
            return _gate_command(args)
        if args.command == "mcp":
            store.close()
            return _mcp_command(args)
        if args.command == "serve":
            from ledgerlens.api.server import serve

            store.close()
            return serve(args.db, args.host, args.port)
    finally:
        try:
            store.close()
        except Exception:
            pass
    return 1


def _run_command(args: argparse.Namespace) -> int:
    if args.command == "demo":
        result = run_demo(args.db, client_id=args.client_id, llm=args.llm)
    else:
        result = run_reconciliation(args.db, client_id=args.client_id, sources=args.source, llm=args.llm)
    if result["llm_backend"] != args.llm:
        print(f"Note: LLM backend '{args.llm}' is not available; the fake adjudicator was used.", file=sys.stderr)
    print(result["report"])
    print(f"Run ID: {result['run_id']}")
    print(f"Status: {result['status']}")
    return 0


def _export_command(args: argparse.Namespace) -> int:
    ndjson = export_normalized_events(args.db, args.run_id)
    if args.output == "-":
        print(ndjson, end="")
        return 0
    output_path = Path(args.output)
    if output_path.parent:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(ndjson, encoding="utf-8")
    print(f"Exported normalized events to {output_path}")
    return 0


def _gate_command(args: argparse.Namespace) -> int:
    try:
        if args.command == "review-complete":
            result = complete_review(args.db, args.run_id, reviewer=args.reviewer, note=args.note)
            print(result["report"])
            print(f"Run ID: {result['run_id']}")
            print(f"Status: {result['status']}")
            return 0
        if args.command == "graph-history":
            for entry in graph_history(args.db, args.run_id):
                print(f"{entry['step']:>3} {entry['node']:<32} {entry['stage'] or '-':<32} {entry['checkpoint_id']} {entry['created_at']}")
            return 0
        record = get_run(args.db, args.run_id)
        print(f"Run ID: {record['id']}")
        print(f"Client: {record['client_id']}")
        print(f"Status: {record['status']}")
        print(f"Open review tasks: {record['open_review_tasks']}")
        return 0
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _mcp_command(_args: argparse.Namespace) -> int:
    try:
        from ledgerlens.mcp.server import main as mcp_main
    except ImportError as exc:
        print(f"The MCP review server is not available in this build ({exc}).", file=sys.stderr)
        return 1
    mcp_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
