import copy
import json
import unittest

from metrics.golden import OUTPUT_PATH, build_headline, validate_headline


class HeadlineMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.headline = build_headline()

    def test_built_headline_conforms_to_card_schema(self):
        self.assertEqual(validate_headline(self.headline), [])

    def test_headline_is_deterministic_across_runs(self):
        self.assertEqual(build_headline(), self.headline)

    def test_committed_headline_matches_fresh_build(self):
        self.assertTrue(OUTPUT_PATH.exists(), "run `make golden` to produce metrics/headline.json")
        committed = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(committed, self.headline, "metrics/headline.json is stale; run `make golden` and commit it")

    def test_headline_reports_expected_panels(self):
        self.assertIn("golden_checks", self.headline["kpis"])
        self.assertIn("schema_conformance", self.headline["kpis"])
        labels = [row["label"] for row in self.headline["bars"]["rows"]]
        self.assertIn("Straight-through matches", labels)
        self.assertIn("Review required", labels)
        statuses = {row["label"]: row["status"] for row in self.headline["facts"]["rows"]}
        self.assertEqual(statuses["Precision / recall / F1"], "pending")

    def test_validator_rejects_bad_accent(self):
        bad = copy.deepcopy(self.headline)
        bad["kpis"]["golden_checks"]["accent"] = "green"
        self.assertTrue(any("accent" in problem for problem in validate_headline(bad)))

    def test_validator_rejects_bad_status(self):
        bad = copy.deepcopy(self.headline)
        bad["facts"]["rows"][0]["status"] = "done"
        self.assertTrue(any("status" in problem for problem in validate_headline(bad)))

    def test_validator_rejects_bar_value_over_max(self):
        bad = copy.deepcopy(self.headline)
        bad["bars"]["rows"][0]["value"] = bad["bars"]["rows"][0]["max"] + 1
        self.assertTrue(any("exceeds max" in problem for problem in validate_headline(bad)))

    def test_validator_rejects_missing_required_keys(self):
        bad = copy.deepcopy(self.headline)
        del bad["kpis"]["golden_checks"]["note"]
        problems = validate_headline(bad)
        self.assertTrue(any("missing key 'note'" in problem for problem in problems))
        del bad["bars"]
        self.assertTrue(any("missing top-level key 'bars'" in problem for problem in validate_headline(bad)))


if __name__ == "__main__":
    unittest.main()
