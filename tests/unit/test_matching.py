from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from ledgerlens.agents.workflow import ReconciliationWorkflow
from ledgerlens.matching.engine import MatchingConfig
from ledgerlens.persistence.store import SQLiteStore


ROOT = Path(__file__).resolve().parents[2]


class MatchingTests(unittest.TestCase):
    def test_demo_reconciliation_uses_multiple_tiers_and_review(self):
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
            tiers = store.decisions_by_tier(result.run_id)
            counts = store.table_counts(result.run_id)
            self.assertEqual(counts["normalized_transactions"], 12)
            self.assertGreaterEqual(counts["candidate_pairs"], 4)
            self.assertTrue(any(key.startswith("exact:") for key in tiers))
            self.assertTrue(any(key.startswith("rule:") for key in tiers))
            self.assertTrue(any(key.startswith("llm:") for key in tiers))
            self.assertGreaterEqual(counts["review_tasks"], 1)
            store.close()


if __name__ == "__main__":
    unittest.main()
