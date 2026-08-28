from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re

from ledgerlens.domain import (
    MappingProfile,
    NormalizedTransaction,
    SourceDiagnostics,
    deterministic_id,
    sha256_digest,
    utc_now,
)
from ledgerlens.ingestion.csv_ingestor import IngestedBatch


@dataclass(frozen=True)
class NormalizationResult:
    transactions: list[NormalizedTransaction]
    diagnostics: SourceDiagnostics


class TransactionNormalizer:
    def __init__(self, profile: MappingProfile):
        self.profile = profile

    def normalize(self, batch: IngestedBatch) -> NormalizationResult:
        transactions: list[NormalizedTransaction] = []
        parse_errors: list[str] = []
        rows_with_missing_reference: list[int] = []
        quality_flag_counts: dict[str, int] = {}

        for raw_transaction in batch.raw_transactions:
            try:
                transaction = self._normalize_row(raw_transaction)
            except ValueError as exc:
                parse_errors.append(f"row {raw_transaction.source_row_number}: {exc}")
                continue

            transactions.append(transaction)
            for flag in transaction.quality_flags:
                quality_flag_counts[flag] = quality_flag_counts.get(flag, 0) + 1
                if flag == "missing_reference":
                    rows_with_missing_reference.append(raw_transaction.source_row_number)

        diagnostics = SourceDiagnostics(
            source_file_id=batch.source_file.id,
            total_rows=batch.diagnostics.total_rows,
            normalized_rows=len(transactions),
            missing_required_counts=batch.diagnostics.missing_required_counts,
            duplicate_external_ids=batch.diagnostics.duplicate_external_ids,
            rows_with_missing_reference=rows_with_missing_reference,
            parse_errors=parse_errors,
            quality_flag_counts=quality_flag_counts,
        )
        return NormalizationResult(transactions=transactions, diagnostics=diagnostics)

    def _normalize_row(self, raw_transaction) -> NormalizedTransaction:
        row = raw_transaction.raw_payload
        posting_date = self._parse_date(self._value(row, "posting_date"), "posting_date")
        value_date = self._parse_optional_date(self._optional_value(row, "value_date")) or posting_date
        amount = self._parse_amount(row)
        direction = self._direction(amount)
        currency = (self._optional_value(row, "currency") or self.profile.default_currency).upper()
        description_raw = self._value(row, "description")
        description_normalized = normalize_description(
            description_raw,
            stopwords=self.profile.description_stopwords,
        )
        reference = self._normalize_reference(
            self._optional_value(row, "reference") or self._extract_reference(description_raw)
        )
        counterparty = self._optional_value(row, "counterparty")
        external_transaction_id = self._optional_value(row, "external_transaction_id")

        quality_flags = []
        if not reference:
            quality_flags.append("missing_reference")
        if not external_transaction_id:
            quality_flags.append("missing_external_transaction_id")

        fingerprint_exact = self._fingerprint_exact(
            amount=amount,
            currency=currency,
            posting_date=posting_date,
            reference=reference,
            counterparty=counterparty,
            description_normalized=description_normalized,
        )
        fingerprint_loose = self._fingerprint_loose(
            amount=amount,
            currency=currency,
            reference=reference,
            counterparty=counterparty,
            description_normalized=description_normalized,
        )
        transaction_id = deterministic_id(
            "txn",
            raw_transaction.id,
            self.profile.client_id,
            self.profile.profile_name,
            external_transaction_id,
            posting_date.isoformat(),
            str(amount),
            currency,
            reference,
        )

        return NormalizedTransaction(
            id=transaction_id,
            raw_transaction_id=raw_transaction.id,
            account_id=self.profile.account_id,
            source_system=self.profile.source_system,
            external_transaction_id=external_transaction_id,
            posting_date=posting_date,
            value_date=value_date,
            amount=amount,
            currency=currency,
            direction=direction,
            description_raw=description_raw,
            description_normalized=description_normalized,
            counterparty=counterparty,
            reference=reference,
            fingerprint_exact=fingerprint_exact,
            fingerprint_loose=fingerprint_loose,
            quality_flags=quality_flags,
            created_at=utc_now(),
        )

    def _value(self, row: dict[str, str], canonical_field: str) -> str:
        value = self._optional_value(row, canonical_field)
        if not value:
            raise ValueError(f"missing required field {canonical_field}")
        return value

    def _optional_value(self, row: dict[str, str], canonical_field: str) -> str | None:
        source_column = self.profile.column_map.get(canonical_field)
        if not source_column:
            return None
        value = row.get(source_column, "").strip()
        return value or None

    def _parse_date(self, value: str, field_name: str) -> date:
        for date_format in self.profile.date_formats:
            try:
                return datetime.strptime(value, date_format).date()
            except ValueError:
                continue
        raise ValueError(f"could not parse {field_name}: {value!r}")

    def _parse_optional_date(self, value: str | None) -> date | None:
        if not value:
            return None
        return self._parse_date(value, "value_date")

    def _parse_amount(self, row: dict[str, str]) -> Decimal:
        if self.profile.amount_strategy == "signed_amount":
            amount_value = self._value(row, "amount")
            return parse_decimal(amount_value)

        debit = parse_decimal(self._optional_value(row, "debit") or "0")
        credit = parse_decimal(self._optional_value(row, "credit") or "0")
        if debit and credit:
            raise ValueError("both debit and credit columns contain non-zero values")
        if debit:
            return -abs(debit) if self.profile.debit_is_negative else abs(debit)
        if credit:
            return abs(credit)
        return Decimal("0.00")

    def _direction(self, amount: Decimal) -> str:
        if amount > 0:
            return "credit"
        if amount < 0:
            return "debit"
        return "zero"

    def _extract_reference(self, description: str) -> str | None:
        for pattern in self.profile.reference_patterns:
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                return match.group(0)
        return None

    def _normalize_reference(self, reference: str | None) -> str | None:
        if not reference:
            return None
        cleaned = reference.strip().upper()
        cleaned = re.sub(r"^REF[:#\s-]*", "", cleaned)
        cleaned = re.sub(r"\s+", "-", cleaned)
        cleaned = cleaned.replace("_", "-")
        for prefix in ("INV", "RMA", "PAYROLL"):
            cleaned = re.sub(fr"^{prefix}-?(\d+)$", fr"{prefix}-\1", cleaned)
        return cleaned

    def _fingerprint_exact(
        self,
        *,
        amount: Decimal,
        currency: str,
        posting_date: date,
        reference: str | None,
        counterparty: str | None,
        description_normalized: str,
    ) -> str:
        evidence_token = reference or normalize_description(counterparty or description_normalized)
        return sha256_digest(
            {
                "kind": "exact",
                "absolute_amount": str(abs(amount)),
                "currency": currency,
                "posting_date": posting_date.isoformat(),
                "evidence_token": evidence_token,
            }
        )

    def _fingerprint_loose(
        self,
        *,
        amount: Decimal,
        currency: str,
        reference: str | None,
        counterparty: str | None,
        description_normalized: str,
    ) -> str:
        token_source = reference or counterparty or description_normalized
        tokens = sorted(set(normalize_description(token_source).split()))
        return sha256_digest(
            {
                "kind": "loose",
                "absolute_amount": str(abs(amount)),
                "currency": currency,
                "tokens": tokens[:6],
            }
        )


def normalize_description(description: str, stopwords: list[str] | None = None) -> str:
    stopword_set = {word.lower() for word in stopwords or []}
    lowered = description.lower()
    tokenized = re.sub(r"[^a-z0-9]+", " ", lowered)
    tokens = [token for token in tokenized.split() if token not in stopword_set]
    return " ".join(tokens)


def parse_decimal(value: str) -> Decimal:
    cleaned = value.strip().replace(",", "").replace("$", "")
    if not cleaned:
        return Decimal("0.00")
    is_parenthesized = cleaned.startswith("(") and cleaned.endswith(")")
    if is_parenthesized:
        cleaned = "-" + cleaned[1:-1]
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError(f"could not parse amount: {value!r}") from exc

