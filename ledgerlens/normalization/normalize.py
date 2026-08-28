from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from ledgerlens.domain.models import NormalizedTransaction, RawTransaction, new_id


@dataclass(frozen=True)
class MappingProfile:
    name: str
    client_id: str
    source_system: str
    account_id: str
    currency: str
    columns: dict[str, str]
    date_formats: list[str]
    amount_tolerance: Decimal = Decimal("1.00")
    date_window_days: int = 3

    @classmethod
    def from_file(cls, path: str | Path) -> "MappingProfile":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            name=data["name"],
            client_id=data["client_id"],
            source_system=data["source_system"],
            account_id=data["account_id"],
            currency=data.get("currency", "USD"),
            columns=data["columns"],
            date_formats=data.get("date_formats", ["%Y-%m-%d", "%m/%d/%Y"]),
            amount_tolerance=Decimal(str(data.get("amount_tolerance", "1.00"))),
            date_window_days=int(data.get("date_window_days", 3)),
        )


def normalize_row(run_id: str, raw: RawTransaction, profile: MappingProfile) -> NormalizedTransaction:
    row = raw.raw_payload
    columns = profile.columns
    posting_date = _parse_date(_value(row, columns.get("posting_date")), profile.date_formats)
    value_date = _parse_date(_value(row, columns.get("value_date")), profile.date_formats, required=False)
    amount = _parse_amount(row, columns)
    description_raw = str(_value(row, columns.get("description")) or "")
    description_normalized = normalize_text(description_raw)
    reference = normalize_reference(str(_value(row, columns.get("reference")) or "")) or extract_reference(description_raw)
    external_id = str(_value(row, columns.get("transaction_id")) or "").strip() or None
    counterparty = extract_counterparty(description_normalized)
    direction = "credit" if amount >= 0 else "debit"
    flags = quality_flags(row, posting_date, amount, description_raw, reference, external_id)
    exact = fingerprint_exact(posting_date, amount, profile.currency, reference)
    loose = fingerprint_loose(amount, profile.currency, reference, description_normalized)
    return NormalizedTransaction(
        id=new_id("txn"),
        run_id=run_id,
        raw_transaction_id=raw.id,
        account_id=profile.account_id,
        source_system=profile.source_system,
        external_transaction_id=external_id,
        posting_date=posting_date,
        value_date=value_date,
        amount=amount,
        currency=profile.currency,
        direction=direction,
        description_raw=description_raw,
        description_normalized=description_normalized,
        counterparty=counterparty,
        reference=reference,
        fingerprint_exact=exact,
        fingerprint_loose=loose,
        quality_flags=flags,
    )


def source_diagnostics(transactions: list[NormalizedTransaction]) -> dict[str, Any]:
    ids = [t.external_transaction_id for t in transactions if t.external_transaction_id]
    refs = [t.reference for t in transactions if t.reference]
    missing_reference = sum(1 for t in transactions if not t.reference)
    missing_external_id = sum(1 for t in transactions if not t.external_transaction_id)
    duplicate_external_ids = sorted({value for value in ids if ids.count(value) > 1})
    duplicate_references = sorted({value for value in refs if refs.count(value) > 1})
    sign_mix = {"credit": sum(1 for t in transactions if t.direction == "credit"), "debit": sum(1 for t in transactions if t.direction == "debit")}
    return {
        "record_count": len(transactions),
        "missing_reference": missing_reference,
        "missing_external_id": missing_external_id,
        "duplicate_external_ids": duplicate_external_ids,
        "duplicate_references": duplicate_references,
        "direction_counts": sign_mix,
        "quality_flag_count": sum(len(t.quality_flags) for t in transactions),
    }


def normalize_text(value: str) -> str:
    value = value.lower()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = re.sub(r"\b(ach|credit|debit|payment|pmt|inc|llc|co)\b", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_reference(value: str) -> str | None:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    return cleaned or None


def extract_reference(description: str) -> str | None:
    patterns = [r"\bINV[-\s]?(\d+)\b", r"\bPO[-\s]?(\d+)\b", r"\bTRF[-\s]?(\d+)\b", r"\b([A-Z]{2,5}\d{2,})\b"]
    upper = description.upper()
    for pattern in patterns:
        match = re.search(pattern, upper)
        if match:
            token = match.group(0)
            return normalize_reference(token)
    return None


def extract_counterparty(description_normalized: str) -> str | None:
    tokens = [token for token in description_normalized.split() if not token.isdigit()]
    return " ".join(tokens[:3]) if tokens else None


def fingerprint_exact(posting_date: str, amount: Decimal, currency: str, reference: str | None) -> str:
    material = "|".join([posting_date, str(amount.quantize(Decimal("0.01"))), currency.upper(), reference or ""])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def fingerprint_loose(amount: Decimal, currency: str, reference: str | None, description_normalized: str) -> str:
    major_tokens = " ".join(description_normalized.split()[:4])
    material = "|".join([str(abs(amount).quantize(Decimal("0.01"))), currency.upper(), reference or "", major_tokens])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def raw_hash(row: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def file_hash_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _parse_date(value: Any, formats: list[str], required: bool = True) -> str | None:
    text = str(value or "").strip()
    if not text:
        if required:
            raise ValueError("missing required date")
        return None
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"unsupported date format: {text}")


def _parse_amount(row: dict[str, Any], columns: dict[str, str]) -> Decimal:
    if columns.get("amount"):
        return _decimal(_value(row, columns["amount"]))
    debit_column = columns.get("debit")
    credit_column = columns.get("credit")
    debit = _decimal(_value(row, debit_column), default=Decimal("0")) if debit_column else Decimal("0")
    credit = _decimal(_value(row, credit_column), default=Decimal("0")) if credit_column else Decimal("0")
    return credit - debit


def _decimal(value: Any, default: Decimal | None = None) -> Decimal:
    text = str(value or "").strip().replace(",", "").replace("$", "")
    if text in {"", "-"}:
        if default is not None:
            return default
        raise ValueError("missing amount")
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError(f"invalid amount: {value}") from exc


def _value(row: dict[str, Any], column: str | None) -> Any:
    if not column:
        return None
    return row.get(column)


def quality_flags(
    row: dict[str, Any],
    posting_date: str,
    amount: Decimal,
    description_raw: str,
    reference: str | None,
    external_id: str | None,
) -> list[str]:
    flags: list[str] = []
    if not posting_date:
        flags.append("missing_posting_date")
    if amount == Decimal("0.00"):
        flags.append("zero_amount")
    if not description_raw.strip():
        flags.append("missing_description")
    if not reference:
        flags.append("missing_reference")
    if not external_id:
        flags.append("missing_external_transaction_id")
    return flags

