from pathlib import Path
import unittest

from ledgerlens.ingestion import CSVIngestor, load_mapping_profile


ROOT = Path(__file__).resolve().parents[2]


class IngestionProfileTests(unittest.TestCase):
    def test_loads_client_mapping_profile_with_reconciliation_controls(self):
        profile = load_mapping_profile(ROOT / "configs" / "clients" / "acme_bank.json")

        self.assertEqual(profile.client_id, "acme")
        self.assertEqual(profile.profile_name, "bank_operating")
        self.assertEqual(profile.source_system, "bank")
        self.assertEqual(profile.account_id, "operating_bank")
        self.assertEqual(profile.amount_strategy, "debit_credit")
        self.assertEqual(profile.default_currency, "USD")
        self.assertEqual(profile.amount_tolerance, "0.00")
        self.assertEqual(profile.date_window_days, 3)
        self.assertEqual(profile.column_map["posting_date"], "Posted Date")

    def test_csv_ingestion_preserves_raw_rows_and_file_idempotency(self):
        profile = load_mapping_profile(ROOT / "configs" / "clients" / "acme_bank.json")
        batch = CSVIngestor(profile).ingest(ROOT / "data" / "samples" / "acme_bank_statement.csv")

        self.assertEqual(batch.source_file.client_id, "acme")
        self.assertEqual(batch.source_file.row_count, 6)
        self.assertEqual(batch.source_file.status, "ingested")
        self.assertTrue(batch.source_file.id.startswith("src_"))
        self.assertEqual(len(batch.raw_transactions), 6)
        self.assertEqual(batch.raw_transactions[0].source_row_number, 2)
        self.assertEqual(batch.raw_transactions[0].raw_payload["Posted Date"], "2026-05-01")
        self.assertTrue(batch.raw_transactions[0].raw_hash.startswith("sha256:"))

        second_batch = CSVIngestor(profile).ingest(
            ROOT / "data" / "samples" / "acme_bank_statement.csv"
        )

        self.assertEqual(second_batch.source_file.id, batch.source_file.id)
        self.assertEqual(
            [row.id for row in second_batch.raw_transactions],
            [row.id for row in batch.raw_transactions],
        )

    def test_ingestion_diagnostics_surface_client_data_quality_issues(self):
        profile = load_mapping_profile(ROOT / "configs" / "clients" / "acme_bank.json")
        batch = CSVIngestor(profile).ingest(ROOT / "data" / "samples" / "acme_bank_statement.csv")

        self.assertEqual(batch.diagnostics.total_rows, 6)
        self.assertEqual(batch.diagnostics.duplicate_external_ids, {"BNK-1005": [6, 7]})
        self.assertEqual(batch.diagnostics.missing_required_counts, {})
        self.assertEqual(batch.diagnostics.rows_with_missing_reference, [5])


if __name__ == "__main__":
    unittest.main()
