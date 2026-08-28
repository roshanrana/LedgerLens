from decimal import Decimal
from pathlib import Path
import unittest

from ledgerlens.domain.models import RawTransaction
from ledgerlens.normalization.normalize import MappingProfile, normalize_row, source_diagnostics


ROOT = Path(__file__).resolve().parents[2]


class NormalizationTests(unittest.TestCase):
    def test_bank_row_normalizes_reference_and_fingerprint(self):
        profile = MappingProfile.from_file(ROOT / "configs" / "clients" / "acme_bank.json")
        raw = RawTransaction(
            id="raw_1",
            source_file_id="src_1",
            source_row_number=1,
            raw_payload={
                "Txn ID": "B-1001",
                "Posted": "2026-05-03",
                "Amount": "1,250.00",
                "Memo": "ACH CREDIT ACME INC INV 8127",
                "Reference": "INV-8127",
            },
            raw_hash="hash",
        )
        txn = normalize_row("run_1", raw, profile)
        self.assertEqual(txn.amount, Decimal("1250.00"))
        self.assertEqual(txn.reference, "INV8127")
        self.assertEqual(txn.direction, "credit")
        self.assertEqual(txn.quality_flags, [])
        self.assertTrue(txn.fingerprint_exact)

    def test_source_diagnostics_finds_duplicate_reference(self):
        profile = MappingProfile.from_file(ROOT / "configs" / "clients" / "acme_bank.json")
        rows = []
        for idx in range(2):
            raw = RawTransaction(
                id=f"raw_{idx}",
                source_file_id="src_1",
                source_row_number=idx + 1,
                raw_payload={
                    "Txn ID": f"B-{idx}",
                    "Posted": "2026-05-03",
                    "Amount": "1250.00",
                    "Memo": "ACH CREDIT ACME INC INV 8127",
                    "Reference": "INV8127",
                },
                raw_hash=f"hash_{idx}",
            )
            rows.append(normalize_row("run_1", raw, profile))
        diagnostics = source_diagnostics(rows)
        self.assertEqual(diagnostics["duplicate_references"], ["INV8127"])


if __name__ == "__main__":
    unittest.main()

