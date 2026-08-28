from __future__ import annotations

import argparse
from pathlib import Path

from ledgerlens.api.resources import export_normalized_events, run_demo, run_reconciliation
from ledgerlens.persistence.store import SQLiteStore
from ledgerlens.reporting.report import generate_markdown_report


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / ".ledgerlens" / "ledgerlens.db"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ledgerlens", description="LedgerLens reconciliation CLI")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="Initialize the SQLite database")
    demo = sub.add_parser("demo", help="Run the bundled bank-vs-ledger reconciliation demo")
    demo.add_argument("--client-id", default="acme")
    reconcile = sub.add_parser("reconcile", help="Run reconciliation for custom CSV/profile pairs")
    reconcile.add_argument("--client-id", required=True)
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
    serve_parser = sub.add_parser("serve", help="Run the local LedgerLens JSON API")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)

    store = SQLiteStore(args.db)
    store.initialize()
    try:
        if args.command == "init-db":
            print(f"Initialized {args.db}")
            return 0
        if args.command == "demo":
            store.close()
            result = run_demo(args.db, client_id=args.client_id)
            print(result["report"])
            print(f"Run ID: {result['run_id']}")
            return 0
        if args.command == "reconcile":
            store.close()
            result = run_reconciliation(args.db, client_id=args.client_id, sources=args.source)
            print(result["report"])
            print(f"Run ID: {result['run_id']}")
            return 0
        if args.command == "report":
            print(generate_markdown_report(store, args.run_id))
            return 0
        if args.command == "export-normalized-events":
            store.close()
            ndjson = export_normalized_events(args.db, args.run_id)
            if args.output == "-":
                print(ndjson, end="")
            else:
                output_path = Path(args.output)
                if output_path.parent:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(ndjson, encoding="utf-8")
                print(f"Exported normalized events to {output_path}")
            return 0
        if args.command == "review-list":
            for task in store.list_review_tasks(args.run_id):
                print(f"{task['id']} {task['status']} {task['priority']} {task['suggested_decision']} {task['reason']}")
            return 0
        if args.command == "review-resolve":
            store.resolve_review_task(args.task_id, args.decision, args.notes or "Resolved from CLI", args.reviewer)
            print(f"Resolved {args.task_id} as {args.decision}")
            return 0
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


if __name__ == "__main__":
    raise SystemExit(main())
