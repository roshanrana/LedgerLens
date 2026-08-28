from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256_digest(value: Any) -> str:
    if isinstance(value, bytes):
        payload = value
    else:
        payload = canonical_json(value).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def deterministic_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256(canonical_json(parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:16]}"


@dataclass(frozen=True)
class MappingProfile:
    client_id: str
    profile_name: str
    source_system: str
    account_id: str
    file_type: str
    default_currency: str
    amount_strategy: str
    column_map: dict[str, str]
    date_formats: list[str]
    debit_is_negative: bool = True
    amount_tolerance: str = "0.00"
    date_window_days: int = 3
    required_fields: list[str] = field(default_factory=list)
    reference_patterns: list[str] = field(default_factory=list)
    description_stopwords: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.amount_strategy not in {"debit_credit", "signed_amount"}:
            raise ValueError("amount_strategy must be debit_credit or signed_amount")
        if self.file_type.lower() != "csv":
            raise ValueError("the sidecar currently supports csv profiles only")
        if "posting_date" not in self.column_map:
            raise ValueError("column_map.posting_date is required")
        if "description" not in self.column_map:
            raise ValueError("column_map.description is required")


@dataclass(frozen=True)
class ReconciliationRun:
    id: str
    client_id: str
    status: str = "created"
    created_at: str = field(default_factory=utc_now)
    completed_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceFile:
    id: str
    client_id: str
    source_system: str
    account_id: str
    filename: str
    file_hash: str
    mapping_profile: str
    row_count: int
    status: str = "ingested"
    ingested_at: str = field(default_factory=utc_now)
    run_id: str | None = None


@dataclass(frozen=True)
class RawTransaction:
    id: str
    source_file_id: str
    source_row_number: int
    raw_payload: dict[str, Any]
    raw_hash: str
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class NormalizedTransaction:
    id: str
    raw_transaction_id: str
    account_id: str
    source_system: str
    external_transaction_id: str | None
    posting_date: str | date
    value_date: str | date | None
    amount: Decimal
    currency: str
    direction: str
    description_raw: str
    description_normalized: str
    counterparty: str | None
    reference: str | None
    fingerprint_exact: str
    fingerprint_loose: str
    quality_flags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    run_id: str | None = None


@dataclass(frozen=True)
class CandidatePair:
    id: str
    run_id: str
    left_transaction_id: str
    right_transaction_id: str
    blocking_reason: str
    feature_vector: dict[str, Any]
    candidate_score: float
    created_by: str
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class MatchDecision:
    id: str
    run_id: str
    candidate_pair_id: str
    decision: str
    tier: str
    confidence: float
    reason_code: str
    explanation: str
    evidence: dict[str, Any] = field(default_factory=dict)
    llm_cache_key: str | None = None
    review_task_id: str | None = None
    decided_by: str = "system"
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class ReviewTask:
    id: str
    run_id: str
    candidate_pair_id: str
    priority: str
    status: str
    reason: str
    suggested_decision: str
    assigned_to: str | None = None
    reviewer_decision: str | None = None
    reviewer_notes: str | None = None
    created_at: str = field(default_factory=utc_now)
    resolved_at: str | None = None


@dataclass(frozen=True)
class LLMCacheEntry:
    cache_key: str
    prompt_schema_version: str
    model: str
    input_hash: str
    output_json: dict[str, Any]
    decision: str
    confidence: float
    reason: str
    token_estimate: int
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class SourceDiagnostics:
    source_file_id: str
    total_rows: int
    normalized_rows: int = 0
    missing_required_counts: dict[str, int] = field(default_factory=dict)
    duplicate_external_ids: dict[str, list[int]] = field(default_factory=dict)
    rows_with_missing_reference: list[int] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)
    quality_flag_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class AuditEvent:
    id: str
    run_id: str
    entity_type: str
    entity_id: str
    event_type: str
    actor_type: str
    actor_id: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        entity_type: str,
        entity_id: str,
        event_type: str,
        actor_type: str,
        actor_id: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "AuditEvent":
        return cls(
            id=new_id("audit"),
            run_id=run_id,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            before=before,
            after=after,
            metadata=metadata or {},
        )
