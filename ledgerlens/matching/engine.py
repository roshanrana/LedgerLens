from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from .models import CandidatePair, MatchEvaluation, MatchingPolicy, NormalizedTransaction, stable_hash
from .text import reference_overlap, token_similarity

MatchingConfig = MatchingPolicy


def amount_delta(left: NormalizedTransaction, right: NormalizedTransaction) -> Decimal:
    return abs(left.absolute_amount - right.absolute_amount)


def date_delta_days(left: NormalizedTransaction, right: NormalizedTransaction) -> int:
    return abs((left.posting_date - right.posting_date).days)


def sign_relation(left: NormalizedTransaction, right: NormalizedTransaction) -> str:
    if left.amount == 0 or right.amount == 0:
        return "zero"
    if (left.amount < 0 < right.amount) or (right.amount < 0 < left.amount):
        return "opposite"
    return "same"


def build_feature_vector(
    left: NormalizedTransaction,
    right: NormalizedTransaction,
    policy: MatchingPolicy | None = None,
) -> dict[str, object]:
    policy = policy or MatchingPolicy()
    delta = amount_delta(left, right)
    date_delta = date_delta_days(left, right)
    return {
        "amount_delta": str(delta),
        "date_delta_days": date_delta,
        "same_currency": left.currency == right.currency,
        "amount_within_tolerance": delta <= policy.amount_tolerance,
        "date_within_window": date_delta <= policy.date_window_days,
        "reference_overlap": reference_overlap(left.reference, right.reference),
        "description_similarity": token_similarity(left.description_normalized, right.description_normalized),
        "counterparty_similarity": token_similarity(left.counterparty, right.counterparty),
        "sign_relation": sign_relation(left, right),
        "left_fingerprint_exact": left.fingerprint_exact,
        "right_fingerprint_exact": right.fingerprint_exact,
        "left_fingerprint_loose": left.fingerprint_loose,
        "right_fingerprint_loose": right.fingerprint_loose,
    }


def _blocking_reasons(features: dict[str, object]) -> list[str]:
    reasons: list[str] = []
    if features["amount_within_tolerance"]:
        reasons.append("amount_within_tolerance")
    if features["date_within_window"]:
        reasons.append("date_window")
    if features["reference_overlap"] >= 0.5:
        reasons.append("shared_reference")
    if features["left_fingerprint_loose"] == features["right_fingerprint_loose"]:
        reasons.append("loose_fingerprint")
    if features["description_similarity"] >= 0.55:
        reasons.append("similar_description")
    if features["counterparty_similarity"] >= 0.75:
        reasons.append("similar_counterparty")
    return reasons


def should_create_candidate(features: dict[str, object]) -> bool:
    if not features["same_currency"]:
        return False
    has_amount_and_date = bool(features["amount_within_tolerance"] and features["date_within_window"])
    has_reference = bool(features["reference_overlap"] >= 0.5)
    has_loose_fingerprint = features["left_fingerprint_loose"] == features["right_fingerprint_loose"]
    has_similar_text = bool(features["description_similarity"] >= 0.40 or features["counterparty_similarity"] >= 0.75)
    return has_loose_fingerprint or has_reference or (has_amount_and_date and has_similar_text)


def generate_candidate_pairs(
    left_transactions: Iterable[NormalizedTransaction],
    right_transactions: Iterable[NormalizedTransaction],
    *,
    run_id: str,
    policy: MatchingPolicy | None = None,
) -> list[CandidatePair]:
    policy = policy or MatchingPolicy()
    pairs: list[CandidatePair] = []
    right_by_currency: dict[str, list[NormalizedTransaction]] = {}
    for right in right_transactions:
        right_by_currency.setdefault(right.currency, []).append(right)

    for left in left_transactions:
        for right in right_by_currency.get(left.currency, []):
            if left.id == right.id:
                continue
            features = build_feature_vector(left, right, policy)
            if not should_create_candidate(features):
                continue
            reasons = _blocking_reasons(features)
            pair_id = stable_hash({"run_id": run_id, "left": left.id, "right": right.id})[:16]
            pairs.append(
                CandidatePair(
                    id=f"pair_{pair_id}",
                    run_id=run_id,
                    left=left,
                    right=right,
                    blocking_reason="_".join(reasons) or "same_currency",
                    feature_vector=features,
                    candidate_score=score_pair_features(features, policy),
                )
            )
    pairs.sort(key=lambda pair: (pair.left_transaction_id, pair.right_transaction_id))
    return pairs


def score_pair_features(features: dict[str, object], policy: MatchingPolicy) -> float:
    if not features["same_currency"]:
        return 0.0

    delta = Decimal(str(features["amount_delta"]))
    amount_score = 1.0 if delta <= policy.amount_tolerance else 0.0
    if not amount_score:
        return 0.0

    date_delta = int(features["date_delta_days"])
    date_score = max(0.0, 1.0 - (date_delta / max(policy.date_window_days + 1, 1)))
    ref_score = float(features["reference_overlap"])
    desc_score = float(features["description_similarity"])
    counterparty_score = float(features["counterparty_similarity"])

    score = (
        0.40 * amount_score
        + 0.20 * date_score
        + 0.20 * ref_score
        + 0.15 * desc_score
        + 0.05 * counterparty_score
    )
    return round(min(score, 1.0), 4)


def score_pair(pair: CandidatePair, policy: MatchingPolicy | None = None) -> float:
    policy = policy or MatchingPolicy()
    pair.candidate_score = score_pair_features(pair.feature_vector, policy)
    return pair.candidate_score


class TieredMatcher:
    def __init__(self, policy: MatchingPolicy | None = None):
        self.policy = policy or MatchingPolicy()

    def evaluate(self, pair: CandidatePair) -> MatchEvaluation:
        return (
            self.evaluate_exact(pair)
            or self.evaluate_rule(pair)
            or self.evaluate_fuzzy(pair)
        )

    def evaluate_exact(self, pair: CandidatePair) -> MatchEvaluation | None:
        if pair.feature_vector["left_fingerprint_exact"] != pair.feature_vector["right_fingerprint_exact"]:
            return None
        return MatchEvaluation(
            status="decided",
            decision="match",
            tier="exact",
            confidence=1.0,
            reason_code="exact_fingerprint",
            explanation="Exact normalized fingerprint matched across amount, currency, date, and descriptor.",
            evidence={
                "left_fingerprint_exact": pair.feature_vector["left_fingerprint_exact"],
                "right_fingerprint_exact": pair.feature_vector["right_fingerprint_exact"],
            },
        )

    def evaluate_rule(self, pair: CandidatePair) -> MatchEvaluation | None:
        features = pair.feature_vector
        strict_amount_match = Decimal(str(features["amount_delta"])) == Decimal("0.00")
        if (
            strict_amount_match
            and features["date_within_window"]
            and features["reference_overlap"] >= 0.5
        ):
            return MatchEvaluation(
                status="decided",
                decision="match",
                tier="rule",
                confidence=0.96,
                reason_code="same_reference_date_window",
                explanation="Amounts align, reference tokens overlap, and posting dates are within policy.",
                evidence={
                    "amount_delta": features["amount_delta"],
                    "date_delta_days": features["date_delta_days"],
                    "reference_overlap": features["reference_overlap"],
                    "sign_relation": features["sign_relation"],
                },
            )
        return None

    def evaluate_fuzzy(self, pair: CandidatePair) -> MatchEvaluation:
        score = score_pair(pair, self.policy)
        strict_amount_match = Decimal(str(pair.feature_vector["amount_delta"])) == Decimal("0.00")
        evidence = {
            "candidate_score": score,
            "amount_delta": pair.feature_vector["amount_delta"],
            "date_delta_days": pair.feature_vector["date_delta_days"],
            "reference_overlap": pair.feature_vector["reference_overlap"],
            "description_similarity": pair.feature_vector["description_similarity"],
            "counterparty_similarity": pair.feature_vector["counterparty_similarity"],
        }

        if score >= self.policy.auto_match_threshold and strict_amount_match:
            return MatchEvaluation(
                status="decided",
                decision="match",
                tier="fuzzy",
                confidence=round(min(score, 0.95), 4),
                reason_code="high_fuzzy_score",
                explanation="Weighted fuzzy score exceeded the auto-match threshold.",
                evidence=evidence,
            )
        if score >= self.policy.llm_min_threshold:
            return MatchEvaluation(
                status="ambiguous",
                decision=None,
                tier=None,
                confidence=score,
                reason_code="ambiguous_fuzzy_band",
                explanation="Candidate score is inside the LLM adjudication band.",
                evidence=evidence,
            )
        return MatchEvaluation(
            status="decided",
            decision="no_match",
            tier="fuzzy",
            confidence=round(1.0 - score, 4),
            reason_code="low_fuzzy_score",
            explanation="Weighted fuzzy score fell below the LLM review band.",
            evidence=evidence,
        )


MatchingConfig = MatchingPolicy
