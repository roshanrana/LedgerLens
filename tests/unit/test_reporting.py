from decimal import Decimal
import unittest

from ledgerlens.matching import CandidatePair, MatchDecision, NormalizedTransaction
from ledgerlens.reporting import ReviewTask, build_reconciliation_report


def tx(transaction_id, amount, source_system):
    return NormalizedTransaction(
        id=transaction_id,
        account_id="operating",
        source_system=source_system,
        posting_date="2026-05-01",
        amount=Decimal(amount),
        currency="USD",
        description_raw="Settlement REF42",
        description_normalized="Settlement REF42",
        reference="REF42",
    )


class ReportingTest(unittest.TestCase):
    def test_report_summarizes_tiers_exceptions_and_llm_savings(self):
        left = tx("bank-1", "-42.00", "bank")
        right = tx("ledger-1", "42.00", "ledger")
        pair = CandidatePair(
            id="pair-1",
            run_id="run-report",
            left=left,
            right=right,
            blocking_reason="amount_date_reference",
            feature_vector={"amount_delta": "0.00", "date_delta_days": 0},
            candidate_score=1.0,
            created_by="test",
        )
        decisions = [
            MatchDecision(
                id="decision-1",
                run_id="run-report",
                candidate_pair_id="pair-1",
                decision="match",
                tier="exact",
                confidence=1.0,
                reason_code="exact_fingerprint",
                explanation="Exact fingerprint matched.",
                evidence={},
                decided_by="matching.exact",
            ),
            MatchDecision(
                id="decision-2",
                run_id="run-report",
                candidate_pair_id="pair-2",
                decision="needs_review",
                tier="llm",
                confidence=0.72,
                reason_code="llm_low_confidence",
                explanation="The fake LLM found weak evidence.",
                evidence={"suggested_decision": "needs_review"},
                decided_by="llm.fake",
            ),
        ]
        review_tasks = [
            ReviewTask(
                id="review-1",
                run_id="run-report",
                candidate_pair_id="pair-2",
                priority="medium",
                status="open",
                reason="llm_low_confidence",
                suggested_decision="needs_review",
            )
        ]

        report = build_reconciliation_report(
            run_id="run-report",
            left_transactions=[left],
            right_transactions=[right],
            candidate_pairs=[pair],
            decisions=decisions,
            review_tasks=review_tasks,
            llm_stats={"calls": 1, "cache_hits": 2, "calls_avoided": 2},
            audit_events=[],
        )

        self.assertEqual(report.summary["total_decisions"], 2)
        self.assertEqual(report.summary["unmatched_transactions"], 0)
        self.assertEqual(report.by_tier["exact"], 1)
        self.assertEqual(report.by_decision["needs_review"], 1)
        self.assertEqual(report.llm_metrics["calls_avoided"], 2)
        self.assertEqual(report.exceptions[0]["review_task_id"], "review-1")
        self.assertIn("LLM calls avoided: 2", report.markdown)
        self.assertIn("Unmatched transactions: 0", report.markdown)


if __name__ == "__main__":
    unittest.main()
