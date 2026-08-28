from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from ledgerlens.domain.models import RawTransaction, SourceFile, new_id
from ledgerlens.normalization.normalize import MappingProfile, file_hash_bytes, normalize_row, raw_hash, source_diagnostics
from ledgerlens.persistence.store import SQLiteStore


@dataclass(frozen=True)
class IngestionResult:
    source_file: SourceFile
    raw_count: int
    normalized_count: int
    diagnostics: dict[str, object]


def ingest_csv(store: SQLiteStore, run_id: str, csv_path: str | Path, profile: MappingProfile) -> IngestionResult:
    path = Path(csv_path)
    content = path.read_bytes()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    source = SourceFile(
        id=new_id("src"),
        run_id=run_id,
        client_id=profile.client_id,
        source_system=profile.source_system,
        account_id=profile.account_id,
        filename=path.name,
        file_hash=file_hash_bytes(content),
        mapping_profile=profile.name,
        row_count=len(rows),
    )
    raw_rows = [
        RawTransaction(
            id=new_id("raw"),
            source_file_id=source.id,
            source_row_number=index,
            raw_payload=row,
            raw_hash=raw_hash(row),
        )
        for index, row in enumerate(rows, start=1)
    ]
    normalized_rows = [normalize_row(run_id, raw, profile) for raw in raw_rows]
    diagnostics = source_diagnostics(normalized_rows)
    store.add_source_file(source)
    store.add_raw_transactions(raw_rows)
    store.add_normalized_transactions(normalized_rows)
    store.set_metric(run_id, f"source_diagnostics.{profile.source_system}", diagnostics)
    return IngestionResult(
        source_file=source,
        raw_count=len(raw_rows),
        normalized_count=len(normalized_rows),
        diagnostics=diagnostics,
    )

