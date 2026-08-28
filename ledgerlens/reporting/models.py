from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
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
    created_at: str = field(default_factory=utc_now_iso)
    resolved_at: str | None = None


@dataclass
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
    created_at: str = field(default_factory=utc_now_iso)


@dataclass
class ReconciliationReport:
    run_id: str
    summary: dict[str, Any]
    by_tier: dict[str, int]
    by_decision: dict[str, int]
    exceptions: list[dict[str, Any]]
    llm_metrics: dict[str, int]
    insights: list[str]
    audit_summary: dict[str, int]
    markdown: str
