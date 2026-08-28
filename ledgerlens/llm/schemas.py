from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from ledgerlens.matching import CandidatePair, MatchingPolicy
from ledgerlens.matching.models import stable_hash


PROMPT_SCHEMA_VERSION = "ledgerlens.llm.adjudication.v1"
MODEL_FAMILY = "fake-deterministic"
ALLOWED_LLM_DECISIONS = {"match", "no_match", "needs_review"}


@dataclass(frozen=True)
class LLMDecision:
    decision: str
    confidence: float
    reason_code: str
    explanation: str
    cache_key: str | None = None
    cache_hit: bool = False

    def __post_init__(self) -> None:
        if self.decision not in ALLOWED_LLM_DECISIONS:
            raise ValueError(f"unsupported LLM decision: {self.decision}")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")

    def with_cache(self, *, cache_key: str, cache_hit: bool) -> "LLMDecision":
        return replace(self, cache_key=cache_key, cache_hit=cache_hit)

    def to_json(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "confidence": self.confidence,
            "reason_code": self.reason_code,
            "explanation": self.explanation,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "LLMDecision":
        return cls(
            decision=payload["decision"],
            confidence=float(payload["confidence"]),
            reason_code=payload["reason_code"],
            explanation=payload["explanation"],
        )


@dataclass(frozen=True)
class LLMAdjudicationRequest:
    pair_id: str
    prompt_schema_version: str
    model_family: str
    left: dict[str, Any]
    right: dict[str, Any]
    computed_features: dict[str, Any]
    policy: dict[str, Any]
    cache_key: str


def build_cache_key(pair: CandidatePair, policy: MatchingPolicy) -> str:
    left_loose = str(pair.feature_vector["left_fingerprint_loose"])
    right_loose = str(pair.feature_vector["right_fingerprint_loose"])
    ordered = sorted([left_loose, right_loose])
    feature_hash = stable_hash(pair.feature_vector)
    return stable_hash(
        {
            "prompt_schema_version": PROMPT_SCHEMA_VERSION,
            "model_family": MODEL_FAMILY,
            "fingerprints": ordered,
            "feature_vector_hash": feature_hash,
            "amount_tolerance": str(policy.amount_tolerance),
            "date_window_days": policy.date_window_days,
        }
    )


def build_adjudication_request(pair: CandidatePair, policy: MatchingPolicy) -> LLMAdjudicationRequest:
    computed_features = dict(pair.feature_vector)
    computed_features["candidate_score"] = pair.candidate_score
    return LLMAdjudicationRequest(
        pair_id=pair.id,
        prompt_schema_version=PROMPT_SCHEMA_VERSION,
        model_family=MODEL_FAMILY,
        left=pair.left.compact(),
        right=pair.right.compact(),
        computed_features=computed_features,
        policy={
            "amount_tolerance": str(policy.amount_tolerance),
            "date_window_days": policy.date_window_days,
            "require_human_review_below_confidence": policy.require_human_review_below_confidence,
            "llm_min_threshold": policy.llm_min_threshold,
        },
        cache_key=build_cache_key(pair, policy),
    )
