from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from .schemas import LLMAdjudicationRequest, LLMDecision

if TYPE_CHECKING:  # pragma: no cover - import cycle guard; live.py imports this module
    from .live import LLMClient


class DeterministicFakeLLM:
    model = "ledgerlens-fake-llm-v1"

    def __init__(self) -> None:
        self.call_count = 0

    def adjudicate(self, request: LLMAdjudicationRequest) -> LLMDecision:
        self.call_count += 1
        features = request.computed_features
        amount_delta = Decimal(str(features["amount_delta"]))
        amount_tolerance = Decimal(str(request.policy["amount_tolerance"]))
        date_delta = int(features["date_delta_days"])
        date_window = int(request.policy["date_window_days"])
        reference = float(features["reference_overlap"])
        description = float(features["description_similarity"])
        score = float(features.get("candidate_score", 0.0))

        if not features["same_currency"] or amount_delta > amount_tolerance:
            return LLMDecision(
                decision="no_match",
                confidence=0.97,
                reason_code="amount_or_currency_conflict",
                explanation="Amount or currency conflicts with reconciliation policy.",
            )

        if reference >= 0.5 and date_delta <= date_window:
            return LLMDecision(
                decision="match",
                confidence=0.91,
                reason_code="reference_and_amount_align",
                explanation="Amounts align, references overlap, and dates are within policy.",
            )

        if score >= 0.78 and description >= 0.72 and date_delta <= date_window:
            return LLMDecision(
                decision="match",
                confidence=0.86,
                reason_code="strong_description_amount_date_align",
                explanation="The descriptions are strongly similar and the amount/date evidence aligns.",
            )

        if score >= float(request.policy["llm_min_threshold"]):
            return LLMDecision(
                decision="needs_review",
                confidence=0.72,
                reason_code="weak_text_without_reference",
                explanation="Amount and date align, but the evidence lacks a reliable reference.",
            )

        return LLMDecision(
            decision="no_match",
            confidence=0.90,
            reason_code="insufficient_similarity",
            explanation="The compact features do not provide enough evidence to match.",
        )


class CachedLLMAdjudicator:
    def __init__(self, client: "LLMClient", cache: Any) -> None:
        self.client = client
        self.cache = cache
        self.cache_hits = 0
        self.cache_misses = 0

    def adjudicate(self, request: LLMAdjudicationRequest) -> LLMDecision:
        cached = self.cache.get(request.cache_key)
        if cached is not None:
            self.cache_hits += 1
            return cached.with_cache(cache_key=request.cache_key, cache_hit=True)

        self.cache_misses += 1
        decision = self.client.adjudicate(request)
        self.cache.set(request.cache_key, decision, token_estimate=_estimate_tokens(request))
        return decision.with_cache(cache_key=request.cache_key, cache_hit=False)

    def stats(self) -> dict[str, int]:
        """Cache counters, plus the client's token usage when the client tracks it.

        ``calls`` stays the number of adjudications sent to the client (cache misses). Live
        clients count every backend round trip, retries included, which lands under
        ``backend_calls`` so the two never get confused.
        """
        cache_stats = self.cache.stats()
        base = {
            "calls": self.cache_misses,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "calls_avoided": self.cache_hits,
            "cache_entries": cache_stats.get("entries", 0),
        }
        usage = getattr(self.client, "usage", None)
        if not isinstance(usage, dict):
            return base
        return {**base, **_usage_stats(usage)}


def _usage_stats(usage: dict[str, Any]) -> dict[str, int]:
    merged = {
        key: int(value)
        for key, value in usage.items()
        if key != "calls" and isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    if isinstance(usage.get("calls"), (int, float)):
        merged["backend_calls"] = int(usage["calls"])
    return merged


def _estimate_tokens(request: LLMAdjudicationRequest) -> int:
    payload_size = len(str(request.left)) + len(str(request.right)) + len(str(request.computed_features))
    return max(1, payload_size // 4)
