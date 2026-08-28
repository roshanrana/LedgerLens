from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from ledgerlens.domain import (
    AuditEvent,
    NormalizedTransaction,
    RawTransaction,
    SourceFile,
    utc_now,
)


class SQLiteLedgerLensStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            for statement in SCHEMA_STATEMENTS:
                connection.execute(statement)

    def create_run(self, *, client_id: str, name: str) -> str:
        run_id = f"run_{uuid4().hex}"
        now = _serialize_datetime(utc_now())
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO reconciliation_runs (id, client_id, name, status, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, client_id, name, "created", now),
            )
        return run_id

    def journal_mode(self) -> str:
        with self._connection() as connection:
            return str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()

    def save_source_file(self, source_file: SourceFile) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO source_files (
                    id,
                    client_id,
                    source_system,
                    account_id,
                    filename,
                    file_hash,
                    mapping_profile,
                    ingested_at,
                    row_count,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_file.id,
                    source_file.client_id,
                    source_file.source_system,
                    source_file.account_id,
                    source_file.filename,
                    source_file.file_hash,
                    source_file.mapping_profile,
                    _serialize_datetime(source_file.ingested_at),
                    source_file.row_count,
                    source_file.status,
                ),
            )

    def get_source_file(self, source_file_id: str) -> SourceFile:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM source_files WHERE id = ?",
                (source_file_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"source file not found: {source_file_id}")
        return _source_file_from_row(row)

    def list_source_files(self, *, client_id: str | None = None) -> list[SourceFile]:
        sql = "SELECT * FROM source_files"
        params: tuple[Any, ...] = ()
        if client_id:
            sql += " WHERE client_id = ?"
            params = (client_id,)
        sql += " ORDER BY ingested_at, id"
        with self._connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_source_file_from_row(row) for row in rows]

    def save_raw_transactions(self, raw_transactions: list[RawTransaction]) -> None:
        with self._connection() as connection:
            connection.executemany(
                """
                INSERT OR IGNORE INTO raw_transactions (
                    id,
                    source_file_id,
                    source_row_number,
                    raw_payload_json,
                    raw_hash,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        transaction.id,
                        transaction.source_file_id,
                        transaction.source_row_number,
                        json.dumps(transaction.raw_payload, sort_keys=True),
                        transaction.raw_hash,
                        _serialize_datetime(transaction.created_at),
                    )
                    for transaction in raw_transactions
                ],
            )

    def list_raw_transactions(self, source_file_id: str) -> list[RawTransaction]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM raw_transactions
                WHERE source_file_id = ?
                ORDER BY source_row_number, id
                """,
                (source_file_id,),
            ).fetchall()
        return [_raw_transaction_from_row(row) for row in rows]

    def save_normalized_transactions(
        self,
        run_id: str,
        transactions: list[NormalizedTransaction],
    ) -> None:
        with self._connection() as connection:
            connection.executemany(
                """
                INSERT OR IGNORE INTO normalized_transactions (
                    run_id,
                    id,
                    raw_transaction_id,
                    account_id,
                    source_system,
                    external_transaction_id,
                    posting_date,
                    value_date,
                    amount,
                    currency,
                    direction,
                    description_raw,
                    description_normalized,
                    counterparty,
                    reference,
                    fingerprint_exact,
                    fingerprint_loose,
                    quality_flags_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        transaction.id,
                        transaction.raw_transaction_id,
                        transaction.account_id,
                        transaction.source_system,
                        transaction.external_transaction_id,
                        _serialize_date(transaction.posting_date),
                        _serialize_date(transaction.value_date),
                        str(transaction.amount),
                        transaction.currency,
                        transaction.direction,
                        transaction.description_raw,
                        transaction.description_normalized,
                        transaction.counterparty,
                        transaction.reference,
                        transaction.fingerprint_exact,
                        transaction.fingerprint_loose,
                        json.dumps(transaction.quality_flags),
                        _serialize_datetime(transaction.created_at),
                    )
                    for transaction in transactions
                ],
            )

    def list_normalized_transactions(self, run_id: str) -> list[NormalizedTransaction]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM normalized_transactions
                WHERE run_id = ?
                ORDER BY posting_date, id
                """,
                (run_id,),
            ).fetchall()
        return [_normalized_transaction_from_row(row) for row in rows]

    def record_audit_event(self, event: AuditEvent) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO audit_events (
                    id,
                    run_id,
                    entity_type,
                    entity_id,
                    event_type,
                    actor_type,
                    actor_id,
                    before_json,
                    after_json,
                    metadata_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.run_id,
                    event.entity_type,
                    event.entity_id,
                    event.event_type,
                    event.actor_type,
                    event.actor_id,
                    _json_or_none(event.before),
                    _json_or_none(event.after),
                    json.dumps(event.metadata, sort_keys=True),
                    _serialize_datetime(event.created_at),
                ),
            )

    def list_audit_events(self, run_id: str) -> list[AuditEvent]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM audit_events
                WHERE run_id = ?
                ORDER BY created_at, id
                """,
                (run_id,),
            ).fetchall()
        return [_audit_event_from_row(row) for row in rows]

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS reconciliation_runs (
        id TEXT PRIMARY KEY,
        client_id TEXT NOT NULL,
        name TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_files (
        id TEXT PRIMARY KEY,
        client_id TEXT NOT NULL,
        source_system TEXT NOT NULL,
        account_id TEXT NOT NULL,
        filename TEXT NOT NULL,
        file_hash TEXT NOT NULL,
        mapping_profile TEXT NOT NULL,
        ingested_at TEXT NOT NULL,
        row_count INTEGER NOT NULL,
        status TEXT NOT NULL,
        UNIQUE (client_id, source_system, account_id, file_hash)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS raw_transactions (
        id TEXT PRIMARY KEY,
        source_file_id TEXT NOT NULL,
        source_row_number INTEGER NOT NULL,
        raw_payload_json TEXT NOT NULL,
        raw_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (source_file_id) REFERENCES source_files(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS normalized_transactions (
        run_id TEXT NOT NULL,
        id TEXT NOT NULL,
        raw_transaction_id TEXT NOT NULL,
        account_id TEXT NOT NULL,
        source_system TEXT NOT NULL,
        external_transaction_id TEXT,
        posting_date TEXT NOT NULL,
        value_date TEXT NOT NULL,
        amount TEXT NOT NULL,
        currency TEXT NOT NULL,
        direction TEXT NOT NULL,
        description_raw TEXT NOT NULL,
        description_normalized TEXT NOT NULL,
        counterparty TEXT,
        reference TEXT,
        fingerprint_exact TEXT NOT NULL,
        fingerprint_loose TEXT NOT NULL,
        quality_flags_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (run_id, id),
        FOREIGN KEY (run_id) REFERENCES reconciliation_runs(id),
        FOREIGN KEY (raw_transaction_id) REFERENCES raw_transactions(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_events (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        actor_type TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        before_json TEXT,
        after_json TEXT,
        metadata_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES reconciliation_runs(id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_source_files_hash_client
    ON source_files(file_hash, client_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_normalized_transactions_account
    ON normalized_transactions(run_id, account_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_normalized_transactions_fingerprint_exact
    ON normalized_transactions(fingerprint_exact)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_normalized_transactions_fingerprint_loose
    ON normalized_transactions(fingerprint_loose)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_audit_events_run_entity
    ON audit_events(run_id, entity_type, entity_id)
    """,
]


def _serialize_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _serialize_date(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _json_or_none(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True)


def _source_file_from_row(row: sqlite3.Row) -> SourceFile:
    return SourceFile(
        id=row["id"],
        client_id=row["client_id"],
        source_system=row["source_system"],
        account_id=row["account_id"],
        filename=row["filename"],
        file_hash=row["file_hash"],
        mapping_profile=row["mapping_profile"],
        ingested_at=_parse_datetime(row["ingested_at"]),
        row_count=row["row_count"],
        status=row["status"],
    )


def _raw_transaction_from_row(row: sqlite3.Row) -> RawTransaction:
    return RawTransaction(
        id=row["id"],
        source_file_id=row["source_file_id"],
        source_row_number=row["source_row_number"],
        raw_payload=json.loads(row["raw_payload_json"]),
        raw_hash=row["raw_hash"],
        created_at=_parse_datetime(row["created_at"]),
    )


def _normalized_transaction_from_row(row: sqlite3.Row) -> NormalizedTransaction:
    return NormalizedTransaction(
        id=row["id"],
        raw_transaction_id=row["raw_transaction_id"],
        account_id=row["account_id"],
        source_system=row["source_system"],
        external_transaction_id=row["external_transaction_id"],
        posting_date=datetime.strptime(row["posting_date"], "%Y-%m-%d").date(),
        value_date=datetime.strptime(row["value_date"], "%Y-%m-%d").date(),
        amount=Decimal(row["amount"]),
        currency=row["currency"],
        direction=row["direction"],
        description_raw=row["description_raw"],
        description_normalized=row["description_normalized"],
        counterparty=row["counterparty"],
        reference=row["reference"],
        fingerprint_exact=row["fingerprint_exact"],
        fingerprint_loose=row["fingerprint_loose"],
        quality_flags=json.loads(row["quality_flags_json"]),
        created_at=_parse_datetime(row["created_at"]),
    )


def _audit_event_from_row(row: sqlite3.Row) -> AuditEvent:
    before_json = row["before_json"]
    after_json = row["after_json"]
    return AuditEvent(
        id=row["id"],
        run_id=row["run_id"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        event_type=row["event_type"],
        actor_type=row["actor_type"],
        actor_id=row["actor_id"],
        before=json.loads(before_json) if before_json else None,
        after=json.loads(after_json) if after_json else None,
        metadata=json.loads(row["metadata_json"]),
        created_at=_parse_datetime(row["created_at"]),
    )
