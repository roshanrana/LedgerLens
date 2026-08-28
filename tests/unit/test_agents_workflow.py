from decimal import Decimal
import unittest

from ledgerlens.agents import ReconciliationWorkflow
from ledgerlens.llm import CachedLLMAdjudicator, DeterministicFakeLLM, InMemoryLLMCache
from ledgerlens.matching import MatchingPolicy, NormalizedTransaction


def tx(transaction_id, amount, posting_date, description, *, reference="", source_system):
    return NormalizedTransaction(
        id=transaction_id,
        account_id="operating",
        source_system=source_system,
        posting_date=posting_date,
        amount=Decimal(amount),
        currency="USD",
        description_raw=description,
        description_normalized=description,
        reference=reference,
    )


class AgentsWorkflowTest(unittest.TestCase):
    def test_workflow_runs_bounded_nodes_and_routes_ambiguous_llm_result_to_review(self):
        left_transactions = [
            tx("bank-exact", "-42.00", "2026-05-01", "Card settlement REF42", reference="REF42", source_system="bank"),
            tx("bank-rule", "-1250.00", "2026-05-01", "ACH PAYMENT ACME INC INV 8127", reference="8127", source_system="bank"),
            tx("bank-ambiguous", "-89.99", "2026-05-10", "SQ COFFEE BAR NYC", source_system="bank"),
        ]
        right_transactions = [
            tx("ledger-exact", "42.00", "2026-05-01", "Card settlement REF42", reference="REF42", source_system="ledger"),
            tx("ledger-rule", "1250.00", "2026-05-03", "ACME invoice payment INV-8127", reference="INV-8127", source_system="ledger"),
            tx("ledger-ambiguous", "89.99", "2026-05-11", "Square Coffee Bar New York", source_system="ledger"),
        ]

        policy = MatchingPolicy(date_window_days=3, require_human_review_below_confidence=0.85)
        fake_llm = DeterministicFakeLLM()
        workflow = ReconciliationWorkflow(policy=policy, llm=CachedLLMAdjudicator(fake_llm, InMemoryLLMCache()))

        state = workflow.run(left_transactions, right_transactions, run_id="run-workflow")

        self.assertEqual(
            workflow.node_names,
            [
                "load_run_context",
                "normalize_batch",
                "generate_candidates",
                "apply_exact_matches",
                "apply_rule_matches",
                "score_fuzzy_candidates",
                "adjudicate_ambiguous_pairs",
                "route_review_tasks",
                "surface_unmatched_transactions",
                "persist_decisions",
                "generate_report",
            ],
        )
        self.assertEqual(state.decision_counts["exact"], 1)
        self.assertEqual(state.decision_counts["rule"], 1)
        self.assertEqual(state.decision_counts["llm"], 1)
        self.assertEqual(fake_llm.call_count, 1)
        self.assertEqual(state.review_task_ids, ["review_run-workflow_ledger-ambiguous_bank-ambiguous"])
        self.assertEqual(state.unmatched_transaction_ids, {"left": [], "right": []})
        self.assertEqual(state.llm_budget_remaining, policy.max_llm_calls - 1)
        self.assertIsNotNone(state.report)
        self.assertIn("LedgerLens Reconciliation Report", state.report.markdown)
        self.assertTrue(any(event.event_type == "match.decision_created" for event in state.audit_events))


if __name__ == "__main__":
    unittest.main()
