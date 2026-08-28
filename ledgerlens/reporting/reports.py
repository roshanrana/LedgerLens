from __future__ import annotations

from collections import Counter
from typing import Iterable

from ledgerlens.matching import CandidatePair, MatchDecision, NormalizedTransaction

from .models import AuditEvent, ReconciliationReport, ReviewTask


def build_reconciliation_report(
    *,
    run_id: str,
    left_transactions: Iterable[NormalizedTransaction],
    right_transactions: Iterable[NormalizedTransaction],
    candidate_pairs: Iterable[CandidatePair],
    decisions: Iterable[MatchDecision],
    review_tasks: Iterable[ReviewTask],
    llm_stats: dict[str, int] | None = None,
    audit_events: Iterable[AuditEvent] | None = None,
) -> ReconciliationReport:
    left = list(left_transactions)
    right = list(right_transactions)
    pairs = list(candidate_pairs)
    decision_list = list(decisions)
    reviews = list(review_tasks)
    audits = list(audit_events or [])
    llm_metrics = _llm_metrics(llm_stats or {})

    by_tier = dict(Counter(decision.tier for decision in decision_list))
    by_decision = dict(Counter(decision.decision for decision in decision_list))
    audit_summary = dict(Counter(event.event_type for event in audits))
    unmatched = _unmatched_transaction_ids(left, right, pairs, decision_list)
    matched_count = by_decision.get("match", 0) + by_decision.get("duplicate", 0)
    auto_decisions = sum(1 for decision in decision_list if decision.tier != "human" and decision.decision == "match")
    open_reviews = [task for task in reviews if task.status == "open"]

    summary = {
        "left_transactions": len(left),
        "right_transactions": len(right),
        "candidate_pairs": len(pairs),
        "total_decisions": len(decision_list),
        "matched_decisions": matched_count,
        "open_review_tasks": len(open_reviews),
        "unmatched_transactions": len(unmatched["left"]) + len(unmatched["right"]),
        "unmatched_left_transactions": len(unmatched["left"]),
        "unmatched_right_transactions": len(unmatched["right"]),
        "match_rate": round(matched_count / len(decision_list), 4) if decision_list else 0.0,
        "estimated_manual_minutes_saved": auto_decisions * 2,
    }

    exceptions = [
        {
            "review_task_id": task.id,
            "candidate_pair_id": task.candidate_pair_id,
            "priority": task.priority,
            "reason": task.reason,
            "suggested_decision": task.suggested_decision,
            "status": task.status,
        }
        for task in reviews
    ]

    insights = _build_insights(summary, by_tier, by_decision, llm_metrics)
    markdown = render_markdown_report(
        run_id=run_id,
        summary=summary,
        by_tier=by_tier,
        by_decision=by_decision,
        exceptions=exceptions,
        llm_metrics=llm_metrics,
        insights=insights,
        audit_summary=audit_summary,
    )

    return ReconciliationReport(
        run_id=run_id,
        summary=summary,
        by_tier=by_tier,
        by_decision=by_decision,
        exceptions=exceptions,
        llm_metrics=llm_metrics,
        insights=insights,
        audit_summary=audit_summary,
        markdown=markdown,
    )


def render_markdown_report(
    *,
    run_id: str,
    summary: dict[str, object],
    by_tier: dict[str, int],
    by_decision: dict[str, int],
    exceptions: list[dict[str, object]],
    llm_metrics: dict[str, int],
    insights: list[str],
    audit_summary: dict[str, int],
) -> str:
    lines = [
        "# LedgerLens Reconciliation Report",
        "",
        f"Run ID: {run_id}",
        "",
        "## Summary",
        f"- Left transactions: {summary['left_transactions']}",
        f"- Right transactions: {summary['right_transactions']}",
        f"- Candidate pairs: {summary['candidate_pairs']}",
        f"- Decisions: {summary['total_decisions']}",
        f"- Unmatched transactions: {summary['unmatched_transactions']}",
        f"- Match rate: {summary['match_rate']}",
        f"- Open review tasks: {summary['open_review_tasks']}",
        f"- Estimated manual minutes saved: {summary['estimated_manual_minutes_saved']}",
        "",
        "## Match tiers",
    ]
    lines.extend(_counter_lines(by_tier))
    lines.extend(["", "## Decisions"])
    lines.extend(_counter_lines(by_decision))
    lines.extend(
        [
            "",
            "## LLM Controls",
            f"- LLM calls made: {llm_metrics['calls']}",
            f"- LLM cache hits: {llm_metrics['cache_hits']}",
            f"- LLM calls avoided: {llm_metrics['calls_avoided']}",
            f"- LLM cache entries: {llm_metrics['cache_entries']}",
            "",
            "## Exceptions",
        ]
    )
    if exceptions:
        for item in exceptions:
            lines.append(
                f"- {item['review_task_id']}: {item['priority']} priority, "
                f"{item['reason']} ({item['status']})"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Insights"])
    lines.extend(f"- {insight}" for insight in insights)
    lines.extend(["", "## Audit"])
    lines.extend(_counter_lines(audit_summary))
    return "\n".join(lines)


def _counter_lines(counter: dict[str, int]) -> list[str]:
    if not counter:
        return ["- None"]
    return [f"- {key}: {counter[key]}" for key in sorted(counter)]


def _llm_metrics(stats: dict[str, int]) -> dict[str, int]:
    return {
        "calls": int(stats.get("calls", 0)),
        "cache_hits": int(stats.get("cache_hits", 0)),
        "cache_misses": int(stats.get("cache_misses", stats.get("calls", 0))),
        "calls_avoided": int(stats.get("calls_avoided", stats.get("cache_hits", 0))),
        "cache_entries": int(stats.get("cache_entries", stats.get("entries", 0))),
    }


def _build_insights(
    summary: dict[str, object],
    by_tier: dict[str, int],
    by_decision: dict[str, int],
    llm_metrics: dict[str, int],
) -> list[str]:
    insights = [
        f"{summary['matched_decisions']} candidate decisions resolved as matches or duplicates.",
        f"{summary['open_review_tasks']} low-confidence items remain in the review queue.",
        f"{summary['unmatched_transactions']} transactions have no matched or reviewable counterpart.",
        f"{llm_metrics['calls_avoided']} repeated adjudications were served from cache.",
    ]
    if by_tier.get("exact", 0) or by_tier.get("rule", 0):
        cheap = by_tier.get("exact", 0) + by_tier.get("rule", 0) + by_tier.get("fuzzy", 0)
        insights.append(f"{cheap} decisions were handled before the LLM tier.")
    if by_decision.get("needs_review", 0):
        insights.append("Human review is focused on ambiguous exceptions instead of all transactions.")
    return insights


def _unmatched_transaction_ids(
    left: list[NormalizedTransaction],
    right: list[NormalizedTransaction],
    pairs: list[CandidatePair],
    decisions: list[MatchDecision],
) -> dict[str, list[str]]:
    pair_by_id = {pair.id: pair for pair in pairs}
    covered_ids: set[str] = set()
    for decision in decisions:
        if decision.decision not in {"match", "duplicate", "needs_review"}:
            continue
        pair = pair_by_id.get(decision.candidate_pair_id)
        if pair is None:
            continue
        covered_ids.add(pair.left_transaction_id)
        covered_ids.add(pair.right_transaction_id)
    return {
        "left": [transaction.id for transaction in left if transaction.id not in covered_ids],
        "right": [transaction.id for transaction in right if transaction.id not in covered_ids],
    }
