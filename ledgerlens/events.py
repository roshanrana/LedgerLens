from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Iterable

from ledgerlens.domain import NormalizedTransaction, deterministic_id, sha256_digest


SCHEMA_VERSION = "1.0"
NORMALIZED_TRANSACTION_EVENT = "ledgerlens.transaction.normalized"


def normalized_transaction_event(transaction: NormalizedTransaction) -> dict[str, Any]:
    if not transaction.run_id:
        raise ValueError(f"transaction is missing run_id: {transaction.id}")

    payload = {
        "transaction_id": transaction.id,
        "raw_transaction_id": transaction.raw_transaction_id,
        "account_id": transaction.account_id,
        "source_system": transaction.source_system,
        "external_transaction_id": transaction.external_transaction_id,
        "posting_date": _date_string(transaction.posting_date),
        "value_date": _date_string(transaction.value_date),
        "amount": _amount_string(transaction.amount),
        "currency": transaction.currency,
        "direction": _contract_direction(transaction),
        "description_raw": transaction.description_raw,
        "description_normalized": transaction.description_normalized,
        "counterparty": transaction.counterparty,
        "reference": transaction.reference,
        "fingerprint_exact": transaction.fingerprint_exact,
        "fingerprint_loose": transaction.fingerprint_loose,
        "quality_flags": list(transaction.quality_flags),
    }

    stable_key = sha256_digest(
        {
            "event_type": NORMALIZED_TRANSACTION_EVENT,
            "run_id": transaction.run_id,
            "transaction_id": transaction.id,
            "payload": payload,
        }
    ).removeprefix("sha256:")
    return {
        "event_id": deterministic_id("evt_norm", transaction.run_id, transaction.id),
        "event_type": NORMALIZED_TRANSACTION_EVENT,
        "schema_version": SCHEMA_VERSION,
        "occurred_at": _timestamp_string(transaction.created_at),
        "run_id": transaction.run_id,
        "source": "ledgerlens.normalization",
        "idempotency_key": f"normalized-{stable_key}",
        "payload": payload,
    }


def normalized_transaction_events(transactions: Iterable[NormalizedTransaction]) -> list[dict[str, Any]]:
    return [normalized_transaction_event(transaction) for transaction in transactions]


def normalized_transaction_events_ndjson(transactions: Iterable[NormalizedTransaction]) -> str:
    lines = [
        json.dumps(event, separators=(",", ":"), default=str)
        for event in normalized_transaction_events(transactions)
    ]
    return "\n".join(lines) + ("\n" if lines else "")


def _amount_string(value: Decimal) -> str:
    return format(value, "f")


def _date_string(value: object | None) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _timestamp_string(value: object | None) -> str:
    if value is None:
        raise ValueError("event timestamp is required")
    text = _date_string(value)
    if text is None:
        raise ValueError("event timestamp is required")
    return text.replace("+00:00", "Z")


def _contract_direction(transaction: NormalizedTransaction) -> str:
    if transaction.direction in {"debit", "credit"}:
        return transaction.direction
    return "credit" if transaction.amount >= 0 else "debit"
