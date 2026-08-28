import json
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from ledgerlens.agents.workflow import ReconciliationWorkflow
from ledgerlens.matching.engine import MatchingConfig
from ledgerlens.persistence.store import SQLiteStore


ROOT = Path(__file__).resolve().parents[2]


class GoldenSummaryTests(unittest.TestCase):
    def test_demo_matches_golden_summary_shape(self):
        expected = json.loads((ROOT / "data" / "golden" / "expected_summary.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteStore(Path(tmp) / "test.db")
            store.initialize()
            workflow = ReconciliationWorkflow(store, MatchingConfig(amount_tolerance=Decimal("1.00")))
            result = workflow.run(
                "acme",
                [
                    (ROOT / "data" / "samples" / "acme_bank_statement.csv", ROOT / "configs" / "clients" / "acme_bank.json"),
                    (ROOT / "data" / "samples" / "acme_ledger_export.csv", ROOT / "configs" / "clients" / "acme_ledger.json"),
                ],
            )
            counts = store.table_counts(result.run_id)
            tiers = store.decisions_by_tier(result.run_id)
            self.assertEqual(counts["normalized_transactions"], expected["normalized_transactions"])
            self.assertGreaterEqual(counts["candidate_pairs"], expected["minimum_candidate_pairs"])
            for tier in expected["expected_decision_tiers"]:
                self.assertTrue(any(key.startswith(f"{tier}:") for key in tiers), tier)
            self.assertGreaterEqual(counts["review_tasks"], expected["minimum_review_tasks"])
            store.close()


if __name__ == "__main__":
    unittest.main()
