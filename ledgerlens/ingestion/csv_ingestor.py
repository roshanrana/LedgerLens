from __future__ import annotations

from dataclasses import dataclass
import csv
from pathlib import Path
import re

from ledgerlens.domain import (
    MappingProfile,
    RawTransaction,
    SourceDiagnostics,
    SourceFile,
    deterministic_id,
    sha256_digest,
    utc_now,
)


@dataclass(frozen=True)
class IngestedBatch:
    source_file: SourceFile
    raw_transactions: list[RawTransaction]
    diagnostics: SourceDiagnostics


class CSVIngestor:
    def __init__(self, profile: MappingProfile):
        self.profile = profile

    def ingest(self, file_path: str | Path) -> IngestedBatch:
        path = Path(file_path)
        file_hash = sha256_digest(path.read_bytes())
        source_file_id = deterministic_id(
            "src",
            self.profile.client_id,
            self.profile.source_system,
            self.profile.account_id,
            self.profile.profile_name,
            path.name,
            file_hash,
        )

        rows = self._read_rows(path)
        source_file = SourceFile(
            id=source_file_id,
            client_id=self.profile.client_id,
            source_system=self.profile.source_system,
            account_id=self.profile.account_id,
            filename=path.name,
            file_hash=file_hash,
            mapping_profile=self.profile.profile_name,
            ingested_at=utc_now(),
            row_count=len(rows),
            status="ingested",
        )
        raw_transactions = [
            RawTransaction(
                id=deterministic_id("raw", source_file_id, source_row_number, row),
                source_file_id=source_file_id,
                source_row_number=source_row_number,
                raw_payload=row,
                raw_hash=sha256_digest(row),
                created_at=utc_now(),
            )
            for source_row_number, row in rows
        ]
        diagnostics = self._diagnose(source_file_id, rows)
        return IngestedBatch(source_file, raw_transactions, diagnostics)

    def _read_rows(self, path: Path) -> list[tuple[int, dict[str, str]]]:
        with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            return [
                (index + 2, {key: (value or "").strip() for key, value in row.items()})
                for index, row in enumerate(reader)
            ]

    def _diagnose(self, source_file_id: str, rows: list[tuple[int, dict[str, str]]]) -> SourceDiagnostics:
        missing_required_counts: dict[str, int] = {}
        external_ids: dict[str, list[int]] = {}
        rows_with_missing_reference: list[int] = []

        external_id_column = self.profile.column_map.get("external_transaction_id")
        reference_column = self.profile.column_map.get("reference")
        description_column = self.profile.column_map["description"]

        for source_row_number, row in rows:
            for canonical_field in self.profile.required_fields:
                source_column = self.profile.column_map.get(canonical_field)
                if not source_column or not row.get(source_column, "").strip():
                    missing_required_counts[canonical_field] = (
                        missing_required_counts.get(canonical_field, 0) + 1
                    )

            if external_id_column:
                external_id = row.get(external_id_column, "").strip()
                if external_id:
                    external_ids.setdefault(external_id, []).append(source_row_number)

            reference = row.get(reference_column, "").strip() if reference_column else ""
            description = row.get(description_column, "")
            if not reference and not self._description_contains_reference(description):
                rows_with_missing_reference.append(source_row_number)

        duplicate_external_ids = {
            external_id: source_rows
            for external_id, source_rows in external_ids.items()
            if len(source_rows) > 1
        }

        return SourceDiagnostics(
            source_file_id=source_file_id,
            total_rows=len(rows),
            missing_required_counts=missing_required_counts,
            duplicate_external_ids=duplicate_external_ids,
            rows_with_missing_reference=rows_with_missing_reference,
        )

    def _description_contains_reference(self, description: str) -> bool:
        return any(re.search(pattern, description, re.IGNORECASE) for pattern in self.profile.reference_patterns)

