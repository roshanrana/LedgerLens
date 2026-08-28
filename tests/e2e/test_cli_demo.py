from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class CLIDemoTests(unittest.TestCase):
    def test_cli_demo_generates_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "ledgerlens.db"
            result = subprocess.run(
                [sys.executable, "-m", "ledgerlens.cli", "--db", str(db), "demo"],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            self.assertIn("LedgerLens Reconciliation Report", result.stdout)
            self.assertIn("LLM calls made", result.stdout)
            self.assertIn("Run ID:", result.stdout)

            run_id = _parse_run_id(result.stdout)
            export = subprocess.run(
                [sys.executable, "-m", "ledgerlens.cli", "--db", str(db), "export-normalized-events", run_id],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            events = [json.loads(line) for line in export.stdout.splitlines() if line.strip()]
            self.assertEqual(len(events), 12)
            self.assertEqual(events[0]["event_type"], "ledgerlens.transaction.normalized")


def _parse_run_id(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("Run ID:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError("Run ID was not printed")


if __name__ == "__main__":
    unittest.main()
