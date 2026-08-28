import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ledgerlens.api.server import build_server

ROOT = Path(__file__).resolve().parents[2]


class APIServerTests(unittest.TestCase):
    def test_http_api_runs_demo_and_resolves_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = build_server(Path(tmp) / "ledgerlens.db", port=0)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                demo = _post_json(f"{base_url}/demo", {"client_id": "acme"})
                run_id = demo["run_id"]
                reviews = _get_json(f"{base_url}/review/tasks?run_id={run_id}&status=open")["review_tasks"]
                self.assertEqual(len(reviews), 1)

                resolved = _post_json(
                    f"{base_url}/review/tasks/{reviews[0]['id']}/resolve",
                    {"decision": "no_match", "notes": "Resolved through API", "reviewer": "api-test"},
                )
                self.assertEqual(resolved["decision"]["tier"], "human")

                report = _get_json(f"{base_url}/runs/{run_id}/report")["report"]
                self.assertIn("human:no_match", report)
                self.assertIn("review.resolved", report)

                conflict = _post_json_error(
                    f"{base_url}/review/tasks/{reviews[0]['id']}/resolve",
                    {"decision": "match", "notes": "Conflicting second decision", "reviewer": "api-test"},
                )
                self.assertEqual(conflict["status"], 409)
                self.assertIn("already resolved", conflict["body"]["error"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_http_api_runs_custom_source_pairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = build_server(Path(tmp) / "ledgerlens.db", port=0)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                result = _post_json(
                    f"{base_url}/runs",
                    {
                        "client_id": "acme",
                        "sources": [
                            {
                                "csv_path": str(ROOT / "data" / "samples" / "acme_bank_statement.csv"),
                                "profile_path": str(ROOT / "configs" / "clients" / "acme_bank.json"),
                            },
                            {
                                "csv_path": str(ROOT / "data" / "samples" / "acme_ledger_export.csv"),
                                "profile_path": str(ROOT / "configs" / "clients" / "acme_ledger.json"),
                            },
                        ],
                    },
                )
                self.assertEqual(result["source_count"], 2)
                self.assertIn("LedgerLens Reconciliation Report", result["report"])
                self.assertEqual(result["counts"]["normalized_transactions"], 12)

                ndjson = _get_text(f"{base_url}/runs/{result['run_id']}/events/normalized")
                events = [json.loads(line) for line in ndjson.splitlines() if line.strip()]
                self.assertEqual(len(events), 12)
                self.assertEqual(events[0]["event_type"], "ledgerlens.transaction.normalized")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_http_api_returns_structured_bad_request_for_invalid_run_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = build_server(Path(tmp) / "ledgerlens.db", port=0)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                bad_sources = _post_json_error(f"{base_url}/runs", {"client_id": "acme", "sources": {}})
                self.assertEqual(bad_sources["status"], 400)
                self.assertIn("sources must be a list", bad_sources["body"]["error"])

                malformed = _post_raw(f"{base_url}/runs", b"{not json")
                self.assertEqual(malformed["status"], 400)
                self.assertIn("malformed JSON", malformed["body"]["error"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


def _post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, method="POST", headers={"content-type": "application/json"})
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(url: str) -> dict[str, object]:
    with urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_text(url: str) -> str:
    with urlopen(url, timeout=10) as response:
        return response.read().decode("utf-8")


def _post_json_error(url: str, payload: dict[str, object]) -> dict[str, object]:
    body = json.dumps(payload).encode("utf-8")
    return _post_raw(url, body)


def _post_raw(url: str, body: bytes) -> dict[str, object]:
    request = Request(url, data=body, method="POST", headers={"content-type": "application/json"})
    try:
        with urlopen(request, timeout=10) as response:
            return {"status": response.status, "body": json.loads(response.read().decode("utf-8"))}
    except HTTPError as exc:
        return {"status": exc.code, "body": json.loads(exc.read().decode("utf-8"))}


if __name__ == "__main__":
    unittest.main()
