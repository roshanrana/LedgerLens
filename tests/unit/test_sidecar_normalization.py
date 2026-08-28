from decimal import Decimal
from pathlib import Path
import unittest

from ledgerlens.ingestion import CSVIngestor, load_mapping_profile
from ledgerlens.normalization import TransactionNormalizer


ROOT = Path(__file__).resolve().parents[2]


class SidecarNormalizationTests(unittest.TestCase):
    def test_normalizes_bank_debit_credit_rows_into_canonical_transactions(self):
        profile = load_mapping_profile(ROOT / "configs" / "clients" / "acme_bank.json")
        batch = CSVIngestor(profile).ingest(ROOT / "data" / "samples" / "acme_bank_statement.csv")

        result = TransactionNormalizer(profile).normalize(batch)
        first = result.transactions[0]

        self.assertEqual(len(result.transactions), 6)
        self.assertEqual(first.account_id, "operating_bank")
        self.assertEqual(first.source_system, "bank")
        self.assertEqual(first.external_transaction_id, "BNK-1001")
        self.assertEqual(first.posting_date.isoformat(), "2026-05-01")
        self.assertEqual(first.value_date.isoformat(), "2026-05-01")
        self.assertEqual(first.amount, Decimal("1250.00"))
        self.assertEqual(first.direction, "credit")
        self.assertEqual(first.currency, "USD")
        self.assertEqual(first.description_normalized, "ach credit acme corp inv 8127")
        self.assertEqual(first.counterparty, "ACME CORP")
        self.assertEqual(first.reference, "INV-8127")
        self.assertTrue(first.fingerprint_exact.startswith("sha256:"))
        self.assertTrue(first.fingerprint_loose.startswith("sha256:"))
        self.assertEqual(first.quality_flags, [])

    def test_normalizes_ledger_signed_amount_rows_and_extracts_references(self):
        profile = load_mapping_profile(ROOT / "configs" / "clients" / "acme_ledger.json")
        batch = CSVIngestor(profile).ingest(ROOT / "data" / "samples" / "acme_ledger_export.csv")

        result = TransactionNormalizer(profile).normalize(batch)
        payment = result.transactions[0]
        refund = result.transactions[2]

        self.assertEqual(payment.account_id, "ar_ledger")
        self.assertEqual(payment.amount, Decimal("1250.00"))
        self.assertEqual(payment.direction, "credit")
        self.assertEqual(payment.reference, "INV-8127")
        self.assertEqual(payment.description_normalized, "customer payment acme invoice 8127")
        self.assertEqual(refund.amount, Decimal("-120.00"))
        self.assertEqual(refund.direction, "debit")
        self.assertEqual(refund.reference, "RMA-77")

    def test_normalization_diagnostics_include_parse_and_reference_flags(self):
        profile = load_mapping_profile(ROOT / "configs" / "clients" / "acme_bank.json")
        batch = CSVIngestor(profile).ingest(ROOT / "data" / "samples" / "acme_bank_statement.csv")

        result = TransactionNormalizer(profile).normalize(batch)

        self.assertEqual(result.diagnostics.total_rows, 6)
        self.assertEqual(result.diagnostics.rows_with_missing_reference, [5])
        self.assertEqual(result.diagnostics.normalized_rows, 6)
        self.assertEqual(result.transactions[3].quality_flags, ["missing_reference"])


if __name__ == "__main__":
    unittest.main()
