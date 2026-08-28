import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
REQUIRED_ENVELOPE = {"event_id", "event_type", "schema_version", "occurred_at", "run_id", "source", "idempotency_key", "payload"}
SCHEMA_BY_EVENT_TYPE = {
    "ledgerlens.statement.ingested": "statement-ingested.schema.json",
    "ledgerlens.transaction.normalized": "transaction-normalized.schema.json",
    "ledgerlens.match.candidate_created": "match-candidate-created.schema.json",
    "ledgerlens.match.decision_created": "match-decision-created.schema.json",
    "ledgerlens.review.required": "review-required.schema.json",
    "ledgerlens.review.resolved": "review-resolved.schema.json",
    "ledgerlens.report.generated": "report-generated.schema.json",
}


class EventContractTests(unittest.TestCase):
    def test_example_and_fixture_events_follow_declared_contracts(self):
        event_paths = list((ROOT / "contracts" / "events").glob("*.example.json"))
        event_paths.extend((ROOT / "contracts" / "events" / "fixtures").glob("*.json"))
        self.assertGreater(len(event_paths), 0)

        for path in event_paths:
            event = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(REQUIRED_ENVELOPE.issubset(event.keys()), path.name)
            self.assertIsInstance(event["payload"], dict)
            self.assertTrue(event["event_type"].startswith("ledgerlens."))
            self.assertIn(event["event_type"], SCHEMA_BY_EVENT_TYPE)

            schema_path = ROOT / "contracts" / "schemas" / SCHEMA_BY_EVENT_TYPE[event["event_type"]]
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            self.assertEqual(schema["properties"]["event_type"]["const"], event["event_type"])
            self.assertEqual(schema["properties"]["schema_version"]["const"], event["schema_version"])
            self.assertTrue(set(schema["required"]).issubset(event.keys()), path.name)
            self.assertTrue(set(schema["properties"]["payload"]["required"]).issubset(event["payload"].keys()), path.name)

    def test_schema_declares_required_envelope_fields(self):
        schema = json.loads((ROOT / "contracts" / "schemas" / "event-envelope.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(schema["required"]), REQUIRED_ENVELOPE)

    def test_ndjson_fixture_contains_only_normalized_transaction_events(self):
        path = ROOT / "contracts" / "events" / "fixtures" / "normalized-events.ndjson"
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(lines), 2)
        for line in lines:
            event = json.loads(line)
            self.assertEqual(event["event_type"], "ledgerlens.transaction.normalized")


if __name__ == "__main__":
    unittest.main()
