from __future__ import annotations

from collections import Counter

from ledgerlens.persistence.store import SQLiteStore


def generate_markdown_report(store: SQLiteStore, run_id: str) -> str:
    counts = store.table_counts(run_id)
    tiers = store.decisions_by_tier(run_id)
    metrics = store.metrics(run_id)
    matching = metrics.get("matching", {})
    audit_summary = Counter(event["event_type"] for event in store.list_audit_events(run_id))
    lines = [
        f"# LedgerLens Reconciliation Report",
        "",
        f"Run: `{run_id}`",
        "",
        "## Executive Summary",
        "",
        f"- Source files: {counts.get('source_files', 0)}",
        f"- Normalized transactions: {counts.get('normalized_transactions', 0)}",
        f"- Candidate pairs: {counts.get('candidate_pairs', 0)}",
        f"- Match decisions: {counts.get('match_decisions', 0)}",
        f"- Open review tasks: {len(store.list_review_tasks(run_id, status='open'))}",
        f"- Unmatched transactions: {matching.get('unmatched_transaction_count', 0)}",
        f"- LLM calls made: {matching.get('llm_calls', 0)}",
        f"- LLM cache hits: {matching.get('llm_cache_hits', 0)}",
        "",
        "## Decisions By Tier",
        "",
    ]
    if tiers:
        for key, count in sorted(tiers.items()):
            lines.append(f"- {key}: {count}")
    else:
        lines.append("- No decisions recorded.")
    lines.extend(["", "## Source Diagnostics", ""])
    diagnostics = {key: value for key, value in metrics.items() if key.startswith("source_diagnostics.")}
    if diagnostics:
        for key, value in sorted(diagnostics.items()):
            source = key.split(".", 1)[1]
            lines.append(f"### {source}")
            lines.append("")
            lines.append(f"- Records: {value.get('record_count', value.get('total_rows', 0))}")
            rows_missing_reference = value.get("rows_with_missing_reference", [])
            lines.append(f"- Missing references: {value.get('missing_reference', len(rows_missing_reference))}")
            lines.append(f"- Missing external IDs: {value.get('missing_external_id', 0)}")
            lines.append(f"- Duplicate references: {', '.join(value.get('duplicate_references', [])) or 'none'}")
            lines.append("")
    else:
        lines.append("- No diagnostics recorded.")
    unmatched = matching.get("unmatched_transaction_ids", {})
    if unmatched:
        lines.extend(["## Unmatched Transactions", ""])
        lines.append(f"- Left source: {len(unmatched.get('left', []))}")
        lines.append(f"- Right source: {len(unmatched.get('right', []))}")
        lines.append("")
    lines.extend(
        [
            "## Demo Notes",
            "",
            "- Deterministic tiers handle clear work before the fake LLM adjudicator is consulted.",
            "- Every decision is persisted with evidence and an audit event.",
            "- Review tasks preserve human authority for low-confidence or duplicate-pressure cases.",
            "- The fake LLM contract keeps tests offline while matching the live integration shape.",
            "",
            "## Audit",
            "",
        ]
    )
    if audit_summary:
        for event_type, count in sorted(audit_summary.items()):
            lines.append(f"- {event_type}: {count}")
    else:
        lines.append("- No audit events recorded.")
    return "\n".join(lines)
