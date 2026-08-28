from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .text import canonical_text, reference_key


ALLOWED_DECISIONS = {"match", "no_match", "duplicate", "needs_review", "unmatched"}
ALLOWED_TIERS = {"exact", "rule", "fuzzy", "llm", "human"}


def money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def iso_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class MatchingPolicy:
    amount_tolerance: Decimal | int | float | str = Decimal("0.00")
    date_window_days: int = 3
    auto_match_threshold: float = 0.90
    llm_min_threshold: float = 0.65
    require_human_review_below_confidence: float = 0.85
    max_llm_calls: int = 25

    def __post_init__(self) -> None:
        self.amount_tolerance = money(self.amount_tolerance)
        if self.date_window_days < 0:
            raise ValueError("date_window_days must be non-negative")
        if not 0 <= self.llm_min_threshold <= self.auto_match_threshold <= 1:
            raise ValueError("thresholds must satisfy 0 <= llm_min <= auto_match <= 1")
        if self.max_llm_calls < 0:
            raise ValueError("max_llm_calls must be non-negative")


@dataclass
class NormalizedTransaction:
    id: str
    account_id: str
    source_system: str
    posting_date: date | datetime | str
    amount: Decimal | int | float | str
    currency: str
    description_raw: str
    description_normalized: str = ""
    raw_transaction_id: str | None = None
    external_transaction_id: str | None = None
    value_date: date | datetime | str | None = None
    direction: str | None = None
    counterparty: str = ""
    reference: str = ""
    quality_flags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        self.posting_date = iso_date(self.posting_date)
        self.value_date = iso_date(self.value_date) if self.value_date else None
        self.amount = money(self.amount)
        self.currency = self.currency.upper()
        self.description_normalized = canonical_text(self.description_normalized or self.description_raw)
        if self.direction is None:
            self.direction = "debit" if self.amount < 0 else "credit"

    @property
    def absolute_amount(self) -> Decimal:
        return abs(self.amount)

    @property
    def normalized_reference(self) -> str:
        return reference_key(self.reference)

    @property
    def stable_descriptor(self) -> str:
        reference = self.normalized_reference
        if reference:
            return reference
        counterparty = canonical_text(self.counterparty)
        if counterparty:
            return counterparty
        return " ".join(self.description_normalized.split()[:5])

    @property
    def fingerprint_exact(self) -> str:
        return stable_hash(
            {
                "amount": str(self.absolute_amount),
                "currency": self.currency,
                "posting_date": self.posting_date.isoformat(),
                "descriptor": self.stable_descriptor,
            }
        )

    @property
    def fingerprint_loose(self) -> str:
        return stable_hash(
            {
                "amount": str(self.absolute_amount),
                "currency": self.currency,
                "descriptor": self.stable_descriptor,
            }
        )

    def compact(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "date": self.posting_date.isoformat(),
            "amount": str(self.amount),
            "currency": self.currency,
            "description": self.description_normalized,
            "reference": self.reference,
            "counterparty": self.counterparty,
            "source_system": self.source_system,
        }


@dataclass
class CandidatePair:
    id: str
    run_id: str
    left: NormalizedTransaction
    right: NormalizedTransaction
    blocking_reason: str
    feature_vector: dict[str, Any]
    candidate_score: float = 0.0
    created_by: str = "matching.blocker"
    created_at: str = field(default_factory=utc_now_iso)

    @property
    def left_transaction_id(self) -> str:
        return self.left.id

    @property
    def right_transaction_id(self) -> str:
        return self.right.id


@dataclass
class MatchDecision:
    id: str
    run_id: str
    candidate_pair_id: str
    decision: str
    tier: str
    confidence: float
    reason_code: str
    explanation: str
    evidence: dict[str, Any]
    llm_cache_key: str | None = None
    review_task_id: str | None = None
    decided_by: str = "ledgerlens"
    created_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if self.decision not in ALLOWED_DECISIONS:
            raise ValueError(f"unsupported decision: {self.decision}")
        if self.tier not in ALLOWED_TIERS:
            raise ValueError(f"unsupported tier: {self.tier}")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")


@dataclass
class MatchEvaluation:
    status: str
    decision: str | None
    tier: str | None
    confidence: float
    reason_code: str
    explanation: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_match_decision(
        self,
        *,
        run_id: str,
        pair: CandidatePair,
        decided_by: str,
        decision_id: str | None = None,
        llm_cache_key: str | None = None,
    ) -> MatchDecision:
        if self.status != "decided" or self.decision is None or self.tier is None:
            raise ValueError("only decided evaluations can be converted to MatchDecision")
        return MatchDecision(
            id=decision_id or f"decision_{run_id}_{pair.left_transaction_id}_{pair.right_transaction_id}_{self.tier}",
            run_id=run_id,
            candidate_pair_id=pair.id,
            decision=self.decision,
            tier=self.tier,
            confidence=self.confidence,
            reason_code=self.reason_code,
            explanation=self.explanation,
            evidence=dict(self.evidence),
            llm_cache_key=llm_cache_key,
            decided_by=decided_by,
        )
