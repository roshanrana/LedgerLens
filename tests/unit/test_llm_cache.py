from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ledgerlens.llm import (
    CachedLLMAdjudicator,
    DeterministicFakeLLM,
    InMemoryLLMCache,
    LLMDecision,
    SQLiteLLMCache,
    build_adjudication_request,
)
from ledgerlens.matching import MatchingPolicy, NormalizedTransaction, generate_candidate_pairs


def tx(transaction_id, amount, posting_date, description, *, source_system):
    return NormalizedTransaction(
        id=transaction_id,
        account_id="operating",
        source_system=source_system,
        posting_date=posting_date,
        amount=Decimal(amount),
        currency="USD",
        description_raw=description,
        description_normalized=description,
    )


class LLMCacheTest(unittest.TestCase):
    def test_cached_fake_llm_avoids_duplicate_pair_adjudication(self):
        left = tx("bank-1", "-89.99", "2026-05-10", "SQ COFFEE BAR NYC", source_system="bank")
        right = tx("ledger-1", "89.99", "2026-05-11", "Square Coffee Bar New York", source_system="ledger")
        policy = MatchingPolicy(date_window_days=3)
        pair = generate_candidate_pairs([left], [right], run_id="run-cache", policy=policy)[0]
        request = build_adjudication_request(pair, policy)

        fake = DeterministicFakeLLM()
        adjudicator = CachedLLMAdjudicator(fake, InMemoryLLMCache())

        first = adjudicator.adjudicate(request)
        second = adjudicator.adjudicate(request)

        self.assertEqual(fake.call_count, 1)
        self.assertFalse(first.cache_hit)
        self.assertTrue(second.cache_hit)
        self.assertEqual(first.decision, second.decision)
        self.assertEqual(adjudicator.stats()["cache_hits"], 1)
        self.assertEqual(adjudicator.stats()["calls_avoided"], 1)

    def test_sqlite_llm_cache_persists_structured_decisions(self):
        with TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "llm-cache.sqlite"
            cache = SQLiteLLMCache(cache_path)
            decision = LLMDecision(
                decision="match",
                confidence=0.91,
                reason_code="reference_and_amount_align",
                explanation="Amounts, dates, and references align within policy.",
            )

            cache.set("cache-key-1", decision, token_estimate=120)
            reloaded_cache = SQLiteLLMCache(cache_path)
            reloaded = reloaded_cache.get("cache-key-1")

            self.assertEqual(reloaded, decision)
            self.assertEqual(reloaded_cache.stats()["entries"], 1)


if __name__ == "__main__":
    unittest.main()
