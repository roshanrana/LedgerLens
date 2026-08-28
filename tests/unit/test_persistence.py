from pathlib import Path
import tempfile
import unittest

from ledgerlens.agents.workflow import ReconciliationWorkflow
from ledgerlens.domain.models import MatchDecision
from ledgerlens.persistence.store import SQLiteStore


ROOT = Path(__file__).resolve().parents[2]


class PersistenceTests(unittest.TestCase):
    def test_initialize_enables_core_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteStore(Path(tmp) / "test.db")
            store.initialize()
            run = store.create_run("acme")
            counts = store.table_counts(run.id)
            self.assertEqual(counts["source_files"], 0)
            self.assertEqual(counts["normalized_transactions"], 0)
            store.close()

    def test_persistent_workflow_rolls_back_partial_run_on_late_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = FailingDecisionStore(Path(tmp) / "test.db")
            store.initialize()
            workflow = ReconciliationWorkflow(store)

            with self.assertRaisesRegex(RuntimeError, "forced decision failure"):
                workflow.run(
                    "acme",
                    [
                        (ROOT / "data" / "samples" / "acme_bank_statement.csv", ROOT / "configs" / "clients" / "acme_bank.json"),
                        (ROOT / "data" / "samples" / "acme_ledger_export.csv", ROOT / "configs" / "clients" / "acme_ledger.json"),
                    ],
                )

            for table in [
                "reconciliation_runs",
                "source_files",
                "raw_transactions",
                "normalized_transactions",
                "candidate_pairs",
                "match_decisions",
                "review_tasks",
                "audit_events",
                "run_metrics",
            ]:
                count = store.conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
                self.assertEqual(count, 0, table)
            store.close()


class FailingDecisionStore(SQLiteStore):
    def save_match_decision(self, decision: MatchDecision) -> None:
        raise RuntimeError("forced decision failure")


if __name__ == "__main__":
    unittest.main()
