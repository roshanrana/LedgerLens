from decimal import Decimal
import unittest

from ledgerlens.matching import (
    MatchingPolicy,
    NormalizedTransaction,
    TieredMatcher,
    generate_candidate_pairs,
)


def tx(
    transaction_id,
    amount,
    posting_date,
    description,
    *,
    reference="",
    counterparty="",
    source_system="bank",
):
    return NormalizedTransaction(
        id=transaction_id,
        account_id="operating",
        source_system=source_system,
        posting_date=posting_date,
        amount=Decimal(amount),
        currency="USD",
        description_raw=description,
        description_normalized=description,
        reference=reference,
        counterparty=counterparty,
    )


class MatchingEngineTest(unittest.TestCase):
    def test_exact_fingerprint_match_is_deterministic(self):
        left = tx("bank-1", "-1250.00", "2026-05-01", "ACH PAYMENT ACME INC INV 8127", reference="8127")
        right = tx(
            "ledger-1",
            "1250.00",
            "2026-05-01",
            "ACME invoice payment 8127",
            reference="8127",
            source_system="ledger",
        )

        self.assertEqual(left.fingerprint_exact, right.fingerprint_exact)

        pair = generate_candidate_pairs([left], [right], run_id="run-test")[0]
        decision = TieredMatcher(MatchingPolicy()).evaluate(pair)

        self.assertEqual(decision.decision, "match")
        self.assertEqual(decision.tier, "exact")
        self.assertEqual(decision.confidence, 1.0)
        self.assertEqual(decision.reason_code, "exact_fingerprint")

    def test_rule_match_handles_cross_source_date_lag_and_reference_variants(self):
        left = tx("bank-2", "-1250.00", "2026-05-01", "ACH PAYMENT ACME INC INV 8127", reference="8127")
        right = tx(
            "ledger-2",
            "1250.00",
            "2026-05-03",
            "ACME invoice payment INV-8127",
            reference="INV-8127",
            source_system="ledger",
        )

        pair = generate_candidate_pairs([left], [right], run_id="run-test")[0]
        decision = TieredMatcher(MatchingPolicy(date_window_days=3)).evaluate(pair)

        self.assertEqual(decision.decision, "match")
        self.assertEqual(decision.tier, "rule")
        self.assertGreaterEqual(decision.confidence, 0.95)
        self.assertEqual(decision.reason_code, "same_reference_date_window")
        self.assertEqual(decision.evidence["date_delta_days"], 2)

    def test_fuzzy_scoring_marks_middle_band_as_ambiguous_for_llm(self):
        left = tx("bank-3", "-89.99", "2026-05-10", "SQ COFFEE BAR NYC")
        right = tx(
            "ledger-3",
            "89.99",
            "2026-05-11",
            "Square Coffee Bar New York",
            source_system="ledger",
        )

        policy = MatchingPolicy(date_window_days=3, llm_min_threshold=0.65, auto_match_threshold=0.90)
        pair = generate_candidate_pairs([left], [right], run_id="run-test", policy=policy)[0]
        result = TieredMatcher(policy).evaluate(pair)

        self.assertEqual(result.status, "ambiguous")
        self.assertIsNone(result.decision)
        self.assertGreaterEqual(pair.candidate_score, 0.65)
        self.assertLess(pair.candidate_score, 0.90)
        self.assertGreater(pair.feature_vector["description_similarity"], 0.50)


if __name__ == "__main__":
    unittest.main()
