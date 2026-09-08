import json
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ledgerlens.api.server import build_server


ROOT = Path(__file__).resolve().parents[2]


class CLIReviewGateTests(unittest.TestCase):
    def test_cli_walks_the_review_gate_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "ledgerlens.db")

            demo = _cli(db, "demo", "--llm", "fake")
            self.assertIn("LedgerLens Reconciliation Report", demo)
            run_id = _line_value(demo, "Run ID:")
            self.assertEqual(_line_value(demo, "Status:"), "awaiting_review")

            status = _cli(db, "run-status", run_id)
            self.assertEqual(_line_value(status, "Status:"), "awaiting_review")
            self.assertEqual(_line_value(status, "Open review tasks:"), "1")

            refused = _cli(db, "review-complete", run_id, "--reviewer", "qa", expect_code=1)
            self.assertIn("open review task", refused)

            tasks = [line for line in _cli(db, "review-list", "--run-id", run_id).splitlines() if line.strip()]
            self.assertEqual(len(tasks), 1)
            task_id = tasks[0].split()[0]
            resolved = _cli(db, "review-resolve", task_id, "--decision", "no_match", "--notes", "Different fee", "--reviewer", "qa")
            self.assertIn(f"Resolved {task_id} as no_match", resolved)

            completed = _cli(db, "review-complete", run_id, "--reviewer", "qa", "--note", "Reviewed from the CLI")
            self.assertEqual(_line_value(completed, "Status:"), "completed")
            self.assertIn("human:no_match", completed)
            self.assertIn("run.finalized", completed)

            report = _cli(db, "report", run_id)
            self.assertIn("human:no_match", report)
            self.assertIn("Open review tasks: 0", report)

            history = [line for line in _cli(db, "graph-history", run_id).splitlines() if line.strip()]
            self.assertGreaterEqual(len(history), 13)
            self.assertIn("await_review", history[-2])
            self.assertIn("finalize_run", history[-1])
            self.assertEqual(_line_value(_cli(db, "run-status", run_id), "Status:"), "completed")


class APIReviewGateTests(unittest.TestCase):
    def test_http_api_exposes_run_history_and_review_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = build_server(Path(tmp) / "ledgerlens.db", port=0)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                demo = _post_json(f"{base_url}/demo", {"client_id": "acme"})
                run_id = demo["run_id"]
                self.assertEqual(demo["status"], "awaiting_review")

                run = _get_json(f"{base_url}/runs/{run_id}")
                self.assertEqual(run["status"], "awaiting_review")
                self.assertEqual(run["open_review_tasks"], 1)

                blocked = _post_json_error(f"{base_url}/runs/{run_id}/review/complete", {"reviewer": "api"})
                self.assertEqual(blocked["status"], 409)
                self.assertIn("open review task", blocked["body"]["error"])

                task = _get_json(f"{base_url}/review/tasks?run_id={run_id}&status=open")["review_tasks"][0]
                _post_json(f"{base_url}/review/tasks/{task['id']}/resolve", {"decision": "match", "notes": "Same payment", "reviewer": "api"})

                no_reviewer = _post_json_error(f"{base_url}/runs/{run_id}/review/complete", {"reviewer": ""})
                self.assertEqual(no_reviewer["status"], 409)

                completed = _post_json(f"{base_url}/runs/{run_id}/review/complete", {"reviewer": "api", "note": "ok"})
                self.assertEqual(completed["status"], "completed")
                self.assertIn("human:match", completed["report"])
                self.assertEqual(_get_json(f"{base_url}/runs/{run_id}")["status"], "completed")

                history = _get_json(f"{base_url}/runs/{run_id}/graph/history")["history"]
                self.assertGreaterEqual(len(history), 13)
                self.assertEqual(history[-1]["stage"], "finalize_run")

                missing = _get_json_error(f"{base_url}/runs/run_missing")
                self.assertEqual(missing["status"], 404)
                missing_gate = _post_json_error(f"{base_url}/runs/run_missing/review/complete", {"reviewer": "api"})
                self.assertEqual(missing_gate["status"], 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


def _cli(db: str, *args: str, expect_code: int = 0) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "ledgerlens.cli", "--db", db, *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != expect_code:
        raise AssertionError(f"exit {result.returncode} for {args}: {result.stdout}\n{result.stderr}")
    return result.stdout + result.stderr


def _line_value(output: str, prefix: str) -> str:
    for line in output.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    raise AssertionError(f"{prefix!r} was not printed:\n{output}")


def _post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, method="POST", headers={"content-type": "application/json"})
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(url: str) -> dict[str, object]:
    with urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json_error(url: str) -> dict[str, object]:
    try:
        with urlopen(url, timeout=10) as response:
            return {"status": response.status, "body": json.loads(response.read().decode("utf-8"))}
    except HTTPError as exc:
        return {"status": exc.code, "body": json.loads(exc.read().decode("utf-8"))}


def _post_json_error(url: str, payload: dict[str, object]) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, method="POST", headers={"content-type": "application/json"})
    try:
        with urlopen(request, timeout=10) as response:
            return {"status": response.status, "body": json.loads(response.read().decode("utf-8"))}
    except HTTPError as exc:
        return {"status": exc.code, "body": json.loads(exc.read().decode("utf-8"))}


if __name__ == "__main__":
    unittest.main()
