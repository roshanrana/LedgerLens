from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class CLIReconcileTests(unittest.TestCase):
    def test_cli_reconcile_accepts_custom_source_pairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "ledgerlens.db"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ledgerlens.cli",
                    "--db",
                    str(db),
                    "reconcile",
                    "--client-id",
                    "acme",
                    "--source",
                    str(ROOT / "data" / "samples" / "acme_bank_statement.csv"),
                    str(ROOT / "configs" / "clients" / "acme_bank.json"),
                    "--source",
                    str(ROOT / "data" / "samples" / "acme_ledger_export.csv"),
                    str(ROOT / "configs" / "clients" / "acme_ledger.json"),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )

            self.assertIn("LedgerLens Reconciliation Report", result.stdout)
            self.assertIn("Decisions By Tier", result.stdout)
            self.assertIn("Run ID:", result.stdout)


if __name__ == "__main__":
    unittest.main()
