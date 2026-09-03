from pathlib import Path
import tempfile
import unittest

from ledgerlens.api.resources import get_report, list_review_tasks, resolve_review_task, run_demo


class ReviewResolutionTests(unittest.TestCase):
    def test_api_resources_resolve_review_with_human_decision_and_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ledgerlens.db"
            demo = run_demo(db_path, client_id="acme")
            open_reviews = list_review_tasks(db_path, run_id=demo["run_id"], status="open")
            self.assertEqual(len(open_reviews), 1)

            resolved = resolve_review_task(
                db_path,
                open_reviews[0]["id"],
                decision="no_match",
                notes="Bank fee wording is similar but policy requires manual no-match.",
                reviewer="review-demo",
            )

            self.assertEqual(resolved["decision"]["tier"], "human")
            self.assertEqual(resolved["decision"]["decision"], "no_match")
            self.assertEqual(resolved["review_task"]["status"], "resolved")

            report = get_report(db_path, demo["run_id"])
            self.assertIn("human:no_match", report["report"])
            self.assertIn("Open review tasks: 0", report["report"])
            self.assertIn("review.resolved", report["report"])

            with self.assertRaisesRegex(ValueError, "already resolved"):
                resolve_review_task(
                    db_path,
                    open_reviews[0]["id"],
                    decision="match",
                    notes="Conflicting second resolution",
                    reviewer="review-demo",
                )


if __name__ == "__main__":
    unittest.main()
