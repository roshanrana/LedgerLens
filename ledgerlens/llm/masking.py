"""Data perimeter for anything that leaves the matching engine.

Both the LLM adjudicator request and the MCP review server hand out *masked* pairs built
here, so the redaction policy lives in one place and is versioned. Nothing below this line
may return a raw counterparty, a raw reference, or a description carrying long digit runs.

Frozen contract (docs/05-langgraph-review-gate-design.md section 4): callers may add keys to
the returned dicts only through this module.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

MASKING_VERSION = "ledgerlens.masking.v1"
MAX_DESCRIPTION_CHARS = 80
_DIGIT_RUN = re.compile(r"\d{5,}")
_KEEP_FIELDS = ("id", "date", "amount", "currency", "source_system")


def token_hash(value: str) -> str:
    """Stable, non-reversible token for a free-text identifier (12 hex chars)."""
    normalized = " ".join(str(value).lower().split())
    digest = hashlib.sha256(f"{MASKING_VERSION}|{normalized}".encode()).hexdigest()
    return digest[:12]


def mask_description(description: str) -> str:
    """Normalised description with account-number-like digit runs replaced and length capped."""
    redacted = _DIGIT_RUN.sub("#", " ".join(str(description).split()))
    return redacted[:MAX_DESCRIPTION_CHARS]


def mask_transaction(compact: dict[str, Any]) -> dict[str, Any]:
    """Mask one ``NormalizedTransaction.compact()`` payload.

    Keeps id, date, amount, currency and source_system verbatim (they are what a match is
    decided on); replaces reference and counterparty with hashed tokens; redacts the
    description. The result carries ``masking_version`` so a reader can tell what was applied.
    """
    masked: dict[str, Any] = {field: compact.get(field) for field in _KEEP_FIELDS}
    masked["description"] = mask_description(str(compact.get("description", "")))
    reference = str(compact.get("reference") or "")
    counterparty = str(compact.get("counterparty") or "")
    masked["reference_token"] = token_hash(reference) if reference else ""
    masked["counterparty_token"] = token_hash(counterparty) if counterparty else ""
    masked["masking_version"] = MASKING_VERSION
    return masked


def mask_pair(pair: Any) -> dict[str, Any]:
    """Mask a ``CandidatePair``: both sides plus the computed feature vector and score."""
    features = dict(pair.feature_vector)
    features["candidate_score"] = pair.candidate_score
    return {
        "pair_id": pair.id,
        "run_id": pair.run_id,
        "left": mask_transaction(pair.left.compact()),
        "right": mask_transaction(pair.right.compact()),
        "features": features,
        "blocking_reason": pair.blocking_reason,
        "masking_version": MASKING_VERSION,
    }


__all__ = [
    "MASKING_VERSION",
    "mask_description",
    "mask_pair",
    "mask_transaction",
    "token_hash",
]
