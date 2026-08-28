import json
from pathlib import Path
import tempfile
import unittest

from ledgerlens.api.resources import export_normalized_events, list_normalized_events, run_demo, run_reconciliation


ROOT = Path(__file__).resolve().parents[2]


class RerunAndEventExportTests(unittest.TestCase):
    def test_same_database_demo_runs_are_run_scoped(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ledgerlens.db"

            first = run_demo(db_path, client_id="acme")
            second = run_demo(db_path, client_id="acme")

            self.assertNotEqual(first["run_id"], second["run_id"])
            self.assertEqual(first["counts"]["source_files"], 2)
            self.assertEqual(second["counts"]["source_files"], 2)
            self.assertEqual(first["counts"]["normalized_transactions"], 12)
            self.assertEqual(second["counts"]["normalized_transactions"], 12)
            self.assertGreaterEqual(second["counts"]["audit_events"], 1)
            self.assertIn("Unmatched transactions: 4", second["report"])
            self.assertIn("exceptions.unmatched_detected", second["report"])

    def test_normalized_events_export_matches_go_worker_contract_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ledgerlens.db"
            demo = run_demo(db_path, client_id="acme")

            events = list_normalized_events(db_path, demo["run_id"])
            self.assertEqual(len(events), 12)
            self.assertEqual(len({event["event_id"] for event in events}), 12)
            self.assertTrue(all(event["event_type"] == "ledgerlens.transaction.normalized" for event in events))
            self.assertTrue(all(event["run_id"] == demo["run_id"] for event in events))
            self.assertTrue(all(event["idempotency_key"].startswith("normalized-") for event in events))
            self.assertTrue(all(event["payload"]["transaction_id"] for event in events))

            ndjson = export_normalized_events(db_path, demo["run_id"])
            lines = [json.loads(line) for line in ndjson.splitlines() if line.strip()]
            self.assertEqual(lines, events)

    def test_reconciliation_rejects_unsupported_source_shapes_before_run_creation(self):
        source = (ROOT / "data" / "samples" / "acme_bank_statement.csv", ROOT / "configs" / "clients" / "acme_bank.json")
        ledger = (ROOT / "data" / "samples" / "acme_ledger_export.csv", ROOT / "configs" / "clients" / "acme_ledger.json")

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ledgerlens.db"
            with self.assertRaisesRegex(ValueError, "exactly two"):
                run_reconciliation(db_path, client_id="acme", sources=[source, ledger, source])

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ledgerlens.db"
            with self.assertRaisesRegex(ValueError, "duplicate source/account"):
                run_reconciliation(db_path, client_id="acme", sources=[source, source])


if __name__ == "__main__":
    unittest.main()
