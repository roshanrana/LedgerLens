import json
import unittest
from dataclasses import asdict
from decimal import Decimal

from ledgerlens.llm import (
    MODEL_FAMILY,
    DeterministicFakeLLM,
    LLMAdjudicationRequest,
    build_adjudication_request,
    build_cache_key,
)
from ledgerlens.llm.masking import (
    MASKING_VERSION,
    MAX_DESCRIPTION_CHARS,
    mask_description,
    mask_pair,
    mask_transaction,
    token_hash,
)
from ledgerlens.llm.schemas import PROMPT_SCHEMA_VERSION
from ledgerlens.matching import MatchingPolicy, NormalizedTransaction, generate_candidate_pairs

RAW_COUNTERPARTY_LEFT = "Square Coffee Bar LLC"
RAW_COUNTERPARTY_RIGHT = "Square Coffee Bar"
RAW_REFERENCE = "INV-2026-0451"
ACCOUNT_NUMBER = "4532019876543210"
# Pinned before masking landed: the fake's key and decision for the pair built below.
PRE_MASKING_CACHE_KEY = "960e7a4cdcd71365bd12f74111cda08c8efbe50c42e53513c659cadbc9850855"


def tx(transaction_id, amount, posting_date, description, *, source_system, reference=None, counterparty=None):
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


def sample_pair():
    left = tx(
        "bank-1", "-89.99", "2026-05-10", f"SQ COFFEE BAR NYC {ACCOUNT_NUMBER}",
        source_system="bank", reference=RAW_REFERENCE, counterparty=RAW_COUNTERPARTY_LEFT,
    )
    right = tx(
        "ledger-1", "89.99", "2026-05-11", f"Square Coffee Bar New York {RAW_REFERENCE}",
        source_system="ledger", reference=RAW_REFERENCE, counterparty=RAW_COUNTERPARTY_RIGHT,
    )
    policy = MatchingPolicy(date_window_days=3)
    pair = generate_candidate_pairs([left], [right], run_id="run-mask", policy=policy)[0]
    return pair, policy


class TokenHashTest(unittest.TestCase):
    def test_token_is_stable_and_normalised(self):
        self.assertEqual(token_hash("Square Coffee Bar"), token_hash("square   coffee bar"))
        self.assertEqual(token_hash("INV-1"), token_hash("INV-1"))

    def test_token_is_short_hex_and_not_reversible(self):
        token = token_hash(RAW_COUNTERPARTY_LEFT)
        self.assertEqual(len(token), 12)
        int(token, 16)
        self.assertNotIn("square", token.lower())
        self.assertNotIn("coffee", token.lower())
        self.assertNotEqual(token, token_hash(RAW_COUNTERPARTY_RIGHT))

    def test_token_is_bound_to_masking_version(self):
        self.assertEqual(MASKING_VERSION, "ledgerlens.masking.v1")
        self.assertTrue(MASKING_VERSION.endswith(".v1"))


class MaskDescriptionTest(unittest.TestCase):
    def test_digit_runs_of_five_or_more_are_redacted(self):
        masked = mask_description(f"ACH  DEBIT {ACCOUNT_NUMBER} ref 1234 acct 98765")
        self.assertNotIn(ACCOUNT_NUMBER, masked)
        self.assertNotIn("98765", masked)
        self.assertIn("1234", masked)
        self.assertEqual(masked, "ACH DEBIT # ref 1234 acct #")

    def test_long_descriptions_are_truncated(self):
        masked = mask_description("x" * 500)
        self.assertEqual(len(masked), MAX_DESCRIPTION_CHARS)


class MaskTransactionTest(unittest.TestCase):
    def test_masked_payload_has_no_raw_identifiers(self):
        pair, _ = sample_pair()
        masked = mask_transaction(pair.left.compact())

        self.assertNotIn("reference", masked)
        self.assertNotIn("counterparty", masked)
        serialised = json.dumps(masked)
        self.assertNotIn(RAW_COUNTERPARTY_LEFT, serialised)
        self.assertNotIn(ACCOUNT_NUMBER, serialised)
        self.assertEqual(masked["reference_token"], token_hash(RAW_REFERENCE))
        self.assertEqual(masked["counterparty_token"], token_hash(RAW_COUNTERPARTY_LEFT))
        self.assertEqual(masked["masking_version"], MASKING_VERSION)

    def test_match_relevant_fields_are_kept_verbatim(self):
        pair, _ = sample_pair()
        compact = pair.left.compact()
        masked = mask_transaction(compact)
        for field in ("id", "date", "amount", "currency", "source_system"):
            self.assertEqual(masked[field], compact[field])

    def test_empty_identifiers_become_empty_tokens(self):
        masked = mask_transaction({"id": "t", "description": "", "reference": None, "counterparty": ""})
        self.assertEqual(masked["reference_token"], "")
        self.assertEqual(masked["counterparty_token"], "")

    def test_mask_pair_masks_both_sides_and_keeps_features(self):
        pair, _ = sample_pair()
        masked = mask_pair(pair)
        serialised = json.dumps(masked, default=str)
        self.assertNotIn(RAW_COUNTERPARTY_LEFT, serialised)
        self.assertNotIn(RAW_REFERENCE, serialised)
        self.assertEqual(masked["pair_id"], pair.id)
        self.assertEqual(masked["features"]["candidate_score"], pair.candidate_score)
        self.assertEqual(masked["masking_version"], MASKING_VERSION)


class AdjudicationRequestMaskingTest(unittest.TestCase):
    def test_request_carries_no_raw_counterparty_or_reference(self):
        pair, policy = sample_pair()
        request = build_adjudication_request(pair, policy)
        serialised = json.dumps(asdict(request), default=str)

        for raw in (RAW_COUNTERPARTY_LEFT, RAW_COUNTERPARTY_RIGHT, RAW_REFERENCE, ACCOUNT_NUMBER):
            self.assertNotIn(raw, serialised)
        self.assertEqual(request.left["masking_version"], MASKING_VERSION)
        self.assertEqual(request.right["counterparty_token"], token_hash(RAW_COUNTERPARTY_RIGHT))

    def test_features_policy_and_fake_decision_are_unchanged_by_masking(self):
        pair, policy = sample_pair()
        masked_request = build_adjudication_request(pair, policy)
        unmasked_request = LLMAdjudicationRequest(
            pair_id=masked_request.pair_id,
            prompt_schema_version=PROMPT_SCHEMA_VERSION,
            model_family=MODEL_FAMILY,
            left=pair.left.compact(),
            right=pair.right.compact(),
            computed_features=masked_request.computed_features,
            policy=masked_request.policy,
            cache_key=masked_request.cache_key,
        )
        expected_features = dict(pair.feature_vector, candidate_score=pair.candidate_score)

        self.assertEqual(masked_request.computed_features, expected_features)
        self.assertEqual(masked_request.policy["date_window_days"], 3)
        self.assertEqual(
            DeterministicFakeLLM().adjudicate(masked_request),
            DeterministicFakeLLM().adjudicate(unmasked_request),
        )

    def test_fake_cache_key_is_byte_identical_to_pre_masking_value(self):
        pair, policy = sample_pair()
        request = build_adjudication_request(pair, policy)
        self.assertEqual(request.cache_key, PRE_MASKING_CACHE_KEY)
        self.assertEqual(build_cache_key(pair, policy), PRE_MASKING_CACHE_KEY)
        self.assertEqual(build_cache_key(pair, policy, model_family=MODEL_FAMILY), PRE_MASKING_CACHE_KEY)
        self.assertEqual(request.model_family, MODEL_FAMILY)


if __name__ == "__main__":
    unittest.main()
